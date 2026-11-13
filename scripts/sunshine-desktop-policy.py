#!/usr/bin/python3
"""Reconcile physical GNOME layouts with a headless Sunshine reserve output."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from guard_config import SETTINGS, state_dir, require_host, init_paths, journal_args
from sunshine_layout import atomic_json, normalize_layout, exclusive_output
from sunshine_observer import read_snapshot, input_health
from sunshine_session_display import (Display, LEASE, UNIT, UNIT_FLAGS, lease_lock,
                                      lease_alive, read_lease, restore)

RESERVE = SETTINGS.reserve_connector
LAYOUT = state_dir()/'physical-layout.json'
IDLE_PATH = '/org/gnome/Mutter/IdleMonitor/Core'
IDLE_NAME = 'org.gnome.Mutter.IdleMonitor'

spec = importlib.util.spec_from_file_location('keep_display_awake', Path(__file__).with_name('keep-display-awake.py'))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def physical_layout(display):
    return normalize_layout(display.layout, display.modes, exclude=RESERVE,
                            layout_mode=display.options.get("layout-mode", 1))


def other_stream_active():
    """Protect applications without display hooks; query failures are not idle."""
    invocation = subprocess.check_output(
        ['systemctl', *UNIT_FLAGS, 'show', '-p', 'InvocationID', '--value', UNIT], text=True, timeout=3,
    ).strip()
    if not invocation:
        return False
    result = subprocess.run(
        ['journalctl', '-q', *journal_args(UNIT,SETTINGS.sunshine_scope,invocation), '-o', 'cat',
         '-g', 'CLIENT (DIS)?CONNECTED|Sunshine version:'], text=True, capture_output=True,
        timeout=3, check=False,
    )
    # journalctl -g exits 1 when the stream has never connected. Distinguish
    # that normal empty result from unavailable journal/permission failures.
    if result.returncode and not (result.returncode == 1 and not result.stdout and not result.stderr):
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    active = 0
    for line in result.stdout.splitlines():
        if 'Sunshine version:' in line:
            active = 0  # The HTTP restart re-execs inside the same systemd invocation.
        elif line.endswith('Info: CLIENT CONNECTED'):
            active += 1
        elif line.endswith('Info: CLIENT DISCONNECTED'):
            active = max(0, active - 1)
    return active > 0



class Policy:
    def __init__(self, idle):
        self.idle = idle
        self.last_idle = None
        self.last_tick = None
        self.last_physical = None
        self.pending_return = False
        self.recovery_pending = False
        self.last_error = None
        self.activity_after = 0.
        self.input_seen = None
        self.observer_warning = False

    def rebase_activity(self):
        # Mutter may reset idle while applying a configuration or enabling power.
        # Do not interpret that reset as a later human input event.
        self.last_idle = int(self.idle.GetIdletime())
        self.last_tick = time.monotonic()
        self.activity_after = self.last_tick + 0.5

    def restore_physical(self, display):
        try:
            saved = json.loads(LAYOUT.read_text()) if LAYOUT.exists() else []
            layout = normalize_layout(saved, display.modes, exclude=RESERVE,
                            layout_mode=display.options.get("layout-mode", 1))
            if not layout:
                raise ValueError('No saved physical layout')
            display.apply(layout)
        except (GLib.Error, ValueError, TypeError, KeyError, OSError, IndexError) as error:
            print(f'Sunshine physical layout fallback: {error}', flush=True)
            physical = sorted(set(display.modes) - {RESERVE})
            # Try every attached output: one broken cable/unsupported mode must
            # not prevent the other panel from becoming usable.
            for connector in physical:
                try:
                    display.only(connector, display.mode(connector))
                    break
                except (GLib.Error, ValueError, IndexError):
                    continue
            else:
                raise ValueError('No physical display could be activated')
        confirmed = Display()
        local = physical_layout(confirmed)
        if not local or confirmed.primary == RESERVE:
            raise ValueError('Physical restoration was not confirmed')
        atomic_json(LAYOUT, local)
        self.pending_return = False
        self.rebase_activity()
        print('Sunshine restored and verified the physical layout', flush=True)

    def tick(self):
        # Keep the lease check and every display/config mutation in the same
        # transaction as prepare/restore. A busy owner never blocks this loop.
        try:
            with lease_lock(timeout=.2):
                return self.tick_locked()
        except TimeoutError:
            return True
        except OSError as error:
            print(f'Sunshine display transaction will retry: {type(error).__name__}', flush=True)
            return True

    def tick_locked(self):
        try:
            display = Display()
            physical = set(display.modes) - {RESERVE}
            now = time.monotonic()
            idletime = int(self.idle.GetIdletime())
            # Without input, idletime grows by elapsed time. Comparing only the
            # old/new values misses continuous input and short polling intervals.
            active = ((self.last_idle is None and idletime < 2000) or
                      (self.last_tick is not None and
                       idletime < self.last_idle + (now-self.last_tick)*1000 - 150))
            observer = read_snapshot(now)
            coverage = input_health(observer, now)
            input_covered = coverage in ('ready', 'no_devices')
            if observer is not None:
                event = observer['physical_input_at']
                observed_input = (event > 0 and ((self.input_seen is None and now-event < 2)
                          or (self.input_seen is not None and event > self.input_seen)))
                active = observed_input if input_covered else (active or observed_input)
                self.input_seen = event
            if input_covered:
                self.observer_warning = False
            elif not self.observer_warning:
                print(f'Sunshine input coverage {coverage}; using degraded idle fallback', flush=True)
                self.observer_warning = True
            # In fallback, latch activity even inside the settling window. It
            # may be deferred, but a genuine single input is never consumed.
            returned = self.last_physical is not None and bool(physical-self.last_physical)
            self.last_idle, self.last_tick, self.last_physical = idletime, now, physical
            if active or returned:
                self.pending_return = True
            lease = read_lease()
            if lease:
                if lease_alive(lease):
                    if display.power() != 0:
                        display.power(enable=True)
                    return True
                if not restore(lease.get('token'), locked=True):
                    return True
                display = Display()
            if RESERVE not in display.modes:
                helper.wake()
                helper.sync_primary()
                return True
            power = display.power()
            local = physical_layout(display)
            exclusive = exclusive_output(display.layout, RESERVE)
            if not exclusive and physical and self.pending_return and power != 0:
                # A key can arrive in the same poll that observes DPMS standby.
                # Wake the existing physical layout; never consume that request
                # by switching it off and resetting pending_return.
                display.power(enable=True)
                helper.sync_primary()
                return True
            settled = input_covered or now >= self.activity_after
            want_return = exclusive and bool(physical) and settled and (self.pending_return or self.recovery_pending)
            want_reserve = not exclusive and (not physical or power != 0)
            if (want_return or want_reserve) and other_stream_active():
                if power != 0:
                    display.power(enable=True)
                return True
            if want_return:
                self.restore_physical(display)
                self.recovery_pending = False
            elif want_reserve:
                # Never destroy the last known layout while switching to reserve.
                if local:
                    atomic_json(LAYOUT, local)
                display.only(RESERVE, display.mode(RESERVE))
                Display().power(enable=True)
                self.pending_return = False
                self.rebase_activity()
                print('Sunshine selected the reserve display', flush=True)
            elif local and any(row[4] for row in local):
                if local != display.layout:
                    display.apply(local)
                    local = physical_layout(Display())
                # Persist only confirmed, normalized layouts, using atomic replace.
                if not LAYOUT.exists() or LAYOUT.read_text() != json.dumps(local):
                    atomic_json(LAYOUT, local)
                self.pending_return = False
            elif power != 0:
                display.power(enable=True)
            helper.sync_primary()
            self.last_error = None
        except (GLib.Error, dbus.DBusException, OSError, ValueError, TypeError, KeyError,
                IndexError, StopIteration, subprocess.SubprocessError) as error:
            # Keep recovery requested across transient API errors. Avoid log floods.
            message = str(error)
            if message != self.last_error:
                print(f'Sunshine monitor policy will retry: {message}', flush=True)
                self.last_error = message
        return True


def main():
    require_host()
    init_paths()
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    helper.dbus, helper.GLib, helper.bus = dbus, GLib, bus
    idle = dbus.Interface(bus.get_object(IDLE_NAME, IDLE_PATH), IDLE_NAME)
    policy = Policy(idle)
    # Startup from a poisoned layout should not depend on another input edge.
    try:
        saved = json.loads(LAYOUT.read_text())
        policy.recovery_pending = bool(saved) and sum(bool(row[4]) for row in saved) != 1
    except (OSError, ValueError, TypeError, IndexError):
        policy.recovery_pending = LAYOUT.exists()
    def owner_changed(name, old, new):
        if name == helper.NAME and new:
            policy.last_idle = policy.last_tick = None
            GLib.timeout_add(1000, policy.tick)
            GLib.timeout_add(3500, helper.sync_primary, True)
    bus.add_signal_receiver(owner_changed, signal_name='NameOwnerChanged',
                            dbus_interface='org.freedesktop.DBus', arg0=helper.NAME)
    policy.tick()
    GLib.timeout_add_seconds(1, policy.tick)
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
