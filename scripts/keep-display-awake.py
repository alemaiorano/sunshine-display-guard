#!/usr/bin/python3
"""Keep GNOME displays available to Sunshine without unlocking the session."""
import subprocess
import time
import base64
import http.client
import json
import os
from pathlib import Path
import ssl
import urllib.request
import urllib.error
from guard_config import SETTINGS, runtime_dir, read_credentials
from sunshine_layout import atomic_json
from sunshine_session_display import lease_lock, read_lease, lease_alive
from sunshine_observer import read_snapshot

NAME = 'org.gnome.Mutter.DisplayConfig'
PATH = '/org/gnome/Mutter/DisplayConfig'
RESTART_ATTEMPTS = 4
RESTART_DELAY_SECONDS = 5
restart_source = None
restart_pending = False
restart_after = 0
sync_source = None
sync_force = False
RESTART_STATE = runtime_dir()/'capture-restart.json'



def mark_restart_pending(output=None):
    atomic_json(RESTART_STATE, {'output': output, 'created': time.time()})


def restart_is_pending():
    return restart_pending or RESTART_STATE.exists()


def restart_sunshine(attempt=0):
    """Serialize the API mutation with display ownership, including retries."""
    global restart_source, restart_pending
    restart_source = None
    try:
        with lease_lock(timeout=.2):
            lease = read_lease()
            snapshot = read_snapshot()
            transmitting = (snapshot is not None and snapshot['video_at'] > 0 and
                            time.monotonic()-snapshot['video_at'] < 2)
            if (lease and lease_alive(lease)) or transmitting:
                restart_pending = True
                if not RESTART_STATE.exists():
                    mark_restart_pending()
                restart_source = GLib.timeout_add_seconds(5, restart_sunshine, attempt)
                return False
            return restart_sunshine_locked(attempt)
    except TimeoutError:
        restart_pending = True
        restart_source = GLib.timeout_add_seconds(5, restart_sunshine, attempt)
        return False

def restart_sunshine_locked(attempt=0):
    """Retry startup transport failures without losing the saved connector."""
    global restart_source, restart_pending, restart_after
    restart_source = None
    restart_pending = True
    restart_after = time.monotonic() + 60
    try:
        if not RESTART_STATE.exists():
            mark_restart_pending()
    except OSError as error:
        print('Sunshine restart persistence needs attention: ' + type(error).__name__, flush=True)
        return False
    try:
        credentials = read_credentials(SETTINGS.restart_credentials)
        auth = base64.b64encode((credentials['username'] + ':' + credentials['password']).encode()).decode()
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print('Sunshine restart credentials need attention: ' + type(error).__name__, flush=True)
        return False
    request = urllib.request.Request(f'https://127.0.0.1:{SETTINGS.api_port}/api/restart', data=b'{}',
                headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=5):
            pass
    except http.client.RemoteDisconnected:
        pass  # Sunshine closes HTTP connections while re-executing itself.
    except (OSError, urllib.error.URLError) as error:
        # Bad credentials/requests require intervention, not repeated POSTs.
        if isinstance(error, urllib.error.HTTPError) and error.code < 500:
            print('Sunshine restart rejected: HTTP ' + str(error.code), flush=True)
            return False
        if attempt + 1 < RESTART_ATTEMPTS:
            restart_source = GLib.timeout_add_seconds(
                RESTART_DELAY_SECONDS, restart_sunshine, attempt + 1)
            print('Sunshine restart pending; retry scheduled: ' + type(error).__name__, flush=True)
        else:
            print('Sunshine restart needs attention: retries exhausted (' + type(error).__name__ + ')', flush=True)
        return False
    RESTART_STATE.unlink(missing_ok=True)
    restart_pending = False
    print('Sunshine restart requested', flush=True)
    return False


def request_restart():
    """A new monitor selection supersedes any pending restart retry."""
    global restart_source
    if restart_source is not None:
        GLib.source_remove(restart_source)
        restart_source = None
    restart_sunshine()


def wake():
    if subprocess.run(['systemctl', *SETTINGS.unit_flags, 'is-active', '--quiet', SETTINGS.sunshine_unit]).returncode:
        return False
    try:
        props = dbus.Interface(bus.get_object(NAME, PATH), 'org.freedesktop.DBus.Properties')
        if int(props.Get(NAME, 'PowerSaveMode')) != 0:
            props.Set(NAME, 'PowerSaveMode', dbus.Int32(0))
            print('Display power restored for Sunshine; screen lock unchanged', flush=True)
    except dbus.DBusException:
        pass  # No user compositor before graphical login.
    return False


def sync_primary(force_restart=False):
    """Serialize callbacks as well as policy ticks with stream ownership."""
    global sync_source, sync_force
    if not SETTINGS.follow_primary:
        return False
    sync_force = sync_force or force_restart
    try:
        with lease_lock(timeout=.2):
            lease = read_lease()
            snapshot = read_snapshot()
            transmitting = (snapshot is not None and snapshot['video_at'] > 0 and
                            time.monotonic() - snapshot['video_at'] < 2)
            if (lease and lease_alive(lease)) or transmitting:
                defer_sync()
                return False
            force = sync_force
            sync_force = False
            if sync_source is not None:
                GLib.source_remove(sync_source)
                sync_source = None
            return sync_primary_locked(force)
    except (TimeoutError, OSError):
        defer_sync()
        return False


def defer_sync():
    global sync_source
    if sync_source is None:
        sync_source = GLib.timeout_add_seconds(5, retry_sync)


def retry_sync():
    global sync_source
    sync_source = None
    return sync_primary()


def sync_primary_locked(force_restart=False):
    """Follow GNOME's explicit primary connector, preserving all other settings."""
    try:
        display = dbus.Interface(bus.get_object(NAME, PATH), NAME)
        state = display.GetCurrentState()
        primary = next((str(m[5][0][0]) for m in state[2] if m[4] and m[5]), None)
        if not primary:
            return False
        # GNOME on Xorg can call HDMI-A-2 'HDMI-2'; KMS uses the DRM name.
        if not list(Path('/sys/class/drm').glob('card*-' + primary + '/status')):
            drm_name = primary.replace('HDMI-', 'HDMI-A-', 1) if primary.startswith('HDMI-') else primary
            if list(Path('/sys/class/drm').glob('card*-' + drm_name + '/status')):
                primary = drm_name
            else:
                print('No matching DRM connector for GNOME primary: ' + primary, flush=True)
                return False
        config = Path(SETTINGS.sunshine_config).expanduser()
        text = config.read_text()
        configured = next((line.split('=', 1)[1].strip() for line in text.splitlines()
                           if line.split('=', 1)[0].strip() == 'output_name' and '=' in line), None)
        if configured == primary and not force_restart:
            if restart_is_pending() and restart_source is None and time.monotonic() >= restart_after:
                request_restart()
            return False
        if configured != primary:
            # Record intent BEFORE replacing the capture configuration. A
            # policy process restart must not erase the pending reconciliation.
            mark_restart_pending(primary)
            lines = [line for line in text.splitlines()
                     if not ('=' in line and line.split('=', 1)[0].strip() == 'output_name')]
            lines.append('output_name = ' + primary)
            temporary = config.with_name(config.name + '.primary.tmp')
            temporary.write_text('\n'.join(lines) + '\n')
            temporary.chmod(config.stat().st_mode & 0o777)
            os.replace(temporary, config)
        print('Following GNOME primary display: ' + primary, flush=True)
        request_restart()
    except dbus.DBusException:
        pass  # No user compositor before graphical login.
    except (OSError, ValueError) as error:
        print('Primary monitor sync needs attention: ' + type(error).__name__, flush=True)
    return False


def monitors_changed():
    GLib.timeout_add(1000, sync_primary)


def changed(interface, values, invalidated):
    if interface == NAME and 'PowerSaveMode' in values and int(values['PowerSaveMode']) != 0:
        GLib.timeout_add(250, wake)


def owner_changed(name, old, new):
    if name == NAME and new:
        GLib.timeout_add(1000, wake)
        GLib.timeout_add(3500, sync_primary, True)


def main():
    global dbus, GLib, bus
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    bus.add_signal_receiver(monitors_changed, signal_name='MonitorsChanged',
                        dbus_interface=NAME, path=PATH)
    bus.add_signal_receiver(changed, signal_name='PropertiesChanged',
                        dbus_interface='org.freedesktop.DBus.Properties', path=PATH)
    bus.add_signal_receiver(owner_changed, signal_name='NameOwnerChanged',
                        dbus_interface='org.freedesktop.DBus', arg0=NAME)
    wake()
    sync_primary()
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
