#!/usr/bin/python3
"""Choose a Sunshine display mode for one application session."""
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
import uuid
import signal
import threading

from gi.repository import Gio, GLib
from guard_config import SETTINGS, runtime_dir, init_paths, require_host, journal_args
from sunshine_layout import atomic_json, choose_mode, normalize_layout, exclusive_output
from sunshine_observer import video_health, read_snapshot as read_activity, VIDEO_SECONDS

NAME = "org.gnome.Mutter.DisplayConfig"
PATH = "/org/gnome/Mutter/DisplayConfig"
LEASE = runtime_dir()/"lease.json"
RESERVE = SETTINGS.reserve_connector
UNIT = SETTINGS.sunshine_unit
UNIT_FLAGS = SETTINGS.unit_flags


class Display:
    def __init__(self):
        self.proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None, NAME, PATH, NAME, None,
        )
        self.serial, monitors, logical, self.options = self.call("GetCurrentState").unpack()
        self.modes = {spec[0]: modes for spec, modes, _ in monitors}
        self.layout = []
        for x, y, scale, transform, primary, outputs, _ in logical:
            members = []
            for connector, *_ in outputs:
                current = next(m for m in self.modes[connector] if m[-1].get("is-current"))
                members.append((connector, current[0], {}))
            self.layout.append((x, y, scale, transform, primary, members))

    def call(self, method, value=None):
        return self.proxy.call_sync(method, value, Gio.DBusCallFlags.NONE, 5000, None)

    @property
    def primary(self):
        return next((row[-1][0][0] for row in self.layout if row[4]), None)

    def mode(self, connector, size=None, fps=60):
        return choose_mode(self.modes[connector], size, fps)[0]

    def apply(self, layout):
        layout = normalize_layout(layout, self.modes, layout_mode=self.options.get("layout-mode", 1))
        if not layout:
            raise ValueError('Refusing to disable every monitor')
        options = {}
        # XRandR reports its current mode but rejects any attempt to set it.
        # Mutter defines an absent capability as false, including older backends.
        if self.options.get("supports-changing-layout-mode") and "layout-mode" in self.options:
            options["layout-mode"] = GLib.Variant("u", self.options["layout-mode"])
        self.call("ApplyMonitorsConfig", GLib.Variant(
            "(uua(iiduba(ssa{sv}))a{sv})", (self.serial, 1, layout, options),
        ))

    def only(self, connector, mode):
        self.apply([(0, 0, 1.0, 0, True, [(connector, mode, {})])])

    def power(self, enable=False):
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None, NAME, PATH, "org.freedesktop.DBus.Properties", None,
        )
        if enable:
            proxy.call_sync("Set", GLib.Variant("(ssv)", (NAME, "PowerSaveMode", GLib.Variant("i", 0))),
                            Gio.DBusCallFlags.NONE, 3000, None)
            return 0
        return proxy.call_sync("Get", GLib.Variant("(ss)", (NAME, "PowerSaveMode")),
                               Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]


LOCK = LEASE.with_suffix('.lock')
_lock_context = threading.local()
CAPTURE_RESTART = LEASE.with_name('capture-restart.json')


@contextlib.contextmanager
def lease_lock(timeout=5):
    depth = getattr(_lock_context, 'depth', 0) if getattr(_lock_context, 'pid', None) == os.getpid() else 0
    if depth:
        _lock_context.depth = depth + 1
        try:
            yield
        finally:
            _lock_context.depth -= 1
        return
    with LOCK.open('a') as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Display transaction is busy')
                time.sleep(.025)
        _lock_context.pid = os.getpid()
        _lock_context.depth = 1
        try:
            yield
        finally:
            _lock_context.depth = 0
            fcntl.flock(stream, fcntl.LOCK_UN)


def invocation_id():
    return subprocess.check_output(['systemctl', *UNIT_FLAGS, 'show', '-p', 'InvocationID', '--value', UNIT],
                                   text=True, timeout=3).strip()


def process_start(pid):
    try:
        if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 2**31-1:
            return None
        text = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return text[19] if text[0] != 'Z' else None
    except (OSError, ValueError, IndexError, TypeError, OverflowError):
        return None


def lease_alive(record, invocation=None):
    if not isinstance(record, dict) or not record.get('token'):
        return False
    invocation = invocation_id() if invocation is None else invocation
    if not invocation or record.get('invocation') != invocation:
        return False
    if record.get('status') == 'restoring':
        return False
    if record.get('pid'):
        if not record.get('process_start') or process_start(record['pid']) != record['process_start']:
            return False
        return stream_alive(record)
    try:
        age = (time.monotonic() - record['started_monotonic'] if 'started_monotonic' in record
               else time.time() - record['started'])
        return 0 <= age < 60
    except (TypeError, KeyError):
        return False



def stream_alive(record, now=None):
    """Packet progress is independent of journalctl and the watcher PID.

    Grace accommodates codec setup. Observer failure is bounded to 60 seconds
    since the last verified packet, preventing an endless veto on local access.
    """
    now = time.monotonic() if now is None else now
    started = record.get('started_monotonic')
    if not isinstance(started, (int, float)) or not math.isfinite(started):
        return False
    if 0 <= now - started < 45:
        return True
    health = video_health(record, now)
    confirmed = record.get('health_confirmed_monotonic', started)
    if health is True:
        return True
    # An observer restart briefly publishes no packet history. Preserve a
    # recently verified stream while it warms up, without extending stale video.
    limit = VIDEO_SECONDS if health is False else 60
    return isinstance(confirmed, (int, float)) and math.isfinite(confirmed) and 0 <= now-confirmed < limit


def valid_lease(value):
    if not isinstance(value, dict):
        return False
    for key in ('token', 'invocation'):
        if not isinstance(value.get(key), str) or not 1 <= len(value[key]) <= 128:
            return False
    for key in ('started', 'started_monotonic', 'health_confirmed_monotonic'):
        if key == 'started' or key in value:
            n = value.get(key)
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0:
                return False
    if 'pid' in value:
        pid = value['pid']
        start = value.get('process_start')
        if (isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 2**31-1 or
                not isinstance(start, str) or not start.isdigit() or len(start) > 32):
            return False
    if value.get('status', 'active') not in ('active', 'prepared', 'restoring'):
        return False
    attempts = value.get('attempts', 0)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= 4:
        return False
    if any(key in value for key in ('previous', 'target', 'connector')):
        if not all(isinstance(value.get(k), str) and 0 < len(value[k]) <= 256
                   for k in ('previous', 'target', 'connector')):
            return False
    if 'previous_layout' in value and not isinstance(value['previous_layout'], list):
        return False
    return True

def read_lease():
    try:
        with LEASE.open('rb') as stream:
            raw = stream.read(65537)
        if len(raw)>65536:
            raise ValueError('Lease exceeds 64 KiB')
        value = json.loads(raw)
        if not valid_lease(value):
            raise ValueError('Invalid lease schema')
        return value
    except FileNotFoundError:
        return None
    except (ValueError, TypeError, RecursionError):
        LEASE.replace(LEASE.with_suffix(f'.invalid-{time.time_ns()}.json'))
        return None


def prepare():
    connector = RESERVE
    if not connector:
        raise ValueError("Configure reserve_connector before preparing a session")
    with lease_lock():
        if CAPTURE_RESTART.exists():
            raise RuntimeError('Capture reconciliation pending; retry shortly')
        previous_record = read_lease()
        if previous_record:
            if lease_alive(previous_record):
                raise RuntimeError('A display session is already active; close it before opening another')
            if not restore(previous_record.get('token'), locked=True):
                raise RuntimeError('Display recovery is pending; retry shortly')
        invocation = invocation_id()
        if not invocation:
            raise RuntimeError('Configured Sunshine service is not running')
        record = {'started': time.time(), 'started_monotonic': time.monotonic(),
                  'invocation': invocation, 'token': uuid.uuid4().hex, 'video_port': SETTINGS.video_port}
        atomic_json(LEASE, record)
        try:
            display = Display()
            if exclusive_output(display.layout, connector):
                width = int(os.environ.get('SUNSHINE_CLIENT_WIDTH', 0))
                height = int(os.environ.get('SUNSHINE_CLIENT_HEIGHT', 0))
                fps = int(os.environ.get('SUNSHINE_CLIENT_FPS', 60))
                if width > 0 and height > 0:
                    previous = display.layout[0][-1][0][1]
                    if width>16384 or height>16384:
                        raise ValueError('Client dimensions exceed the supported 16K bound')
                    target = display.mode(connector, (width, height), min(max(fps, 1), 240))
                    # Persist rollback before the mutation, including a full mirror layout.
                    record.update(connector=connector, previous=previous, target=target,
                                  previous_layout=display.layout)
                    atomic_json(LEASE, record)
                    if target != previous:
                        display.only(connector, target)
                    print(f'Sunshine display {connector}: requested {width}x{height}, selected {target}', flush=True)
        except (GLib.Error, KeyError, ValueError, IndexError, StopIteration) as error:
            print(f'Sunshine display preparation skipped: {error}', file=sys.stderr)


def restore(token=None, locked=False):
    if not locked:
        with lease_lock():
            return restore(token, locked=True)
    record = read_lease()
    if not record or (token is not None and record.get('token') != token):
        return True
    try:
        if 'previous' in record:
            display = Display()
            if (exclusive_output(display.layout, record['connector']) and
                    display.layout[0][-1][0][1] == record['target']):
                previous = record.get('previous_layout') or [(0, 0, 1., 0, True,
                             [(record['connector'], record['previous'], {})])]
                display.apply(previous)
    except (GLib.Error, KeyError, ValueError, StopIteration, IndexError) as error:
        record['status'] = 'restoring'
        record['attempts'] = (record.get('attempts', 0) if isinstance(record.get('attempts', 0), int) else 0) + 1
        record['error'] = str(error)
        atomic_json(LEASE, record)
        if record['attempts'] < 4:
            return False
        # Preserve the evidence without keeping a dead session's veto on local input.
        LEASE.replace(LEASE.with_suffix('.recovery.json'))
        print(f'Sunshine display recovery deferred: {error}', file=sys.stderr)
        return True
    LEASE.unlink(missing_ok=True)
    return True


def watch_session(record):
    started = record['started']
    deadline = record.get('started_monotonic', time.monotonic()) + 45
    with subprocess.Popen(
        ["journalctl", "-q", *journal_args(UNIT,SETTINGS.sunshine_scope,record.get('invocation')),
         "--since", f"@{started:.6f}", "-f", "-o", "cat"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as journal, selectors.DefaultSelector() as selector:
        selector.register(journal.stdout, selectors.EVENT_READ)
        active = 0
        connected = False
        pending = b""
        try:
            while True:
                now = time.monotonic()
                if not stream_alive(record, now):
                    return
                if video_health(record, now) is True:
                    connected = True
                    activity = read_activity(now)
                    if activity is not None:
                        record['health_confirmed_monotonic'] = activity['video_at']
                    with lease_lock():
                        current = read_lease()
                        if not current or current.get('token') != record['token']:
                            return
                        if activity is not None:
                            current['health_confirmed_monotonic'] = activity['video_at']
                            atomic_json(LEASE, current)
                if not connected and now > deadline:
                    return
                if not selector.select(1):
                    continue
                chunk = os.read(journal.stdout.fileno(), 8192)
                if not chunk:
                    # A logging process may exit while video remains healthy.
                    # Keep the bounded packet-health watchdog, without spinning
                    # on an EOF descriptor or depending on a journal restart.
                    selector.unregister(journal.stdout)
                    continue
                *lines, pending = (pending + chunk).split(b"\n")
                pending = pending[-8192:]
                disconnected = False
                for line in lines:
                    if line.endswith(b"Info: CLIENT CONNECTED"):
                        active += 1
                        connected = True
                    elif line.endswith(b"Info: CLIENT DISCONNECTED"):
                        active = max(0, active - 1)
                        disconnected = True
                if disconnected and active == 0:
                    return
        finally:
            if journal.poll() is None:
                journal.terminate()
                try:
                    journal.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    journal.kill()
                    journal.wait(timeout=2)


def session():
    with lease_lock():
        record = read_lease()
        if not record or not lease_alive(record):
            raise RuntimeError('No prepared display session')
        if record.get('pid'):
            raise RuntimeError('Display session already has an owner')
        record.update(pid=os.getpid(), process_start=process_start(os.getpid()))
        atomic_json(LEASE, record)
    def stop(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        watch_session(record)
    finally:
        restore(record['token'])


if __name__ == "__main__":
    require_host()
    init_paths()
    {"prepare": prepare, "restore": restore, "session": session}[sys.argv[1]]()
