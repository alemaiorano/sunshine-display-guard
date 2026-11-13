#!/usr/bin/python3
"""Publish timestamps for physical input and Sunshine's outgoing video packets.

The privileged process never writes event codes, key values, packet contents or
addresses. Consumers only read a small root-owned JSON heartbeat in /run.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import time
import uuid

STATE = Path('/run/sunshine-display-guard/observer.json')
BOOT = Path('/proc/sys/kernel/random/boot_id')
EVENT = struct.Struct('@llHHi')
FRESH_SECONDS = 5
VIDEO_SECONDS = 20
SCHEMA = 2


def source_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def input_health(snapshot, now=None):
    """Video heartbeat and input coverage are separate health signals."""
    now = time.monotonic() if now is None else now
    try:
        if snapshot.get('schema') != SCHEMA:
            return 'unknown'
        eligible, opened, errors = (snapshot[k] for k in
                                    ('input_eligible', 'input_opened', 'input_errors'))
        if any(type(n) is not int or n < 0 for n in (eligible, opened, errors)):
            return 'degraded'
        scanned = snapshot['input_scan_at']
        if (isinstance(scanned, bool) or not isinstance(scanned, (int, float)) or
                not math.isfinite(scanned) or not 0 <= now - scanned <= FRESH_SECONDS):
            return 'degraded'
        if errors or opened != eligible:
            return 'degraded'
        return 'ready' if opened else 'no_devices'
    except (KeyError, TypeError, AttributeError):
        return 'unknown'


class InputDevices:
    def __init__(self, selector):
        self.selector = selector
        self.descriptors = {}
        self.identities = {}
        self.absolute = {}
        self.eligible = self.errors = 0
        self.scanned_at = 0.

    def close(self, device):
        fd = self.descriptors.pop(device, None)
        self.identities.pop(device, None)
        if fd is not None:
            try:
                self.selector.unregister(fd)
            except (OSError, KeyError):
                pass
            finally:
                os.close(fd)
            self.absolute = {key: value for key, value in self.absolute.items() if key[0] != fd}

    def scan(self, now):
        candidates = {}
        self.errors = 0
        try:
            for path in Path('/sys/class/input').glob('event*'):
                if physical_device(path / 'device'):
                    device = Path('/dev/input') / path.name
                    try:
                        stat = device.stat()
                        candidates[device] = (stat.st_ino, stat.st_rdev)
                    except OSError:
                        candidates[device] = None
                        self.errors += 1
        except OSError:
            self.errors += 1
        self.eligible = len(candidates)
        for device in list(self.descriptors):
            if candidates.get(device) != self.identities[device]:
                self.close(device)
        for device, identity in candidates.items():
            if device in self.descriptors or identity is None:
                continue
            fd = None
            try:
                fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
                stat = os.fstat(fd)
                if (stat.st_ino, stat.st_rdev) != identity:
                    raise OSError('Input changed while opening')
                self.selector.register(fd, selectors.EVENT_READ, device)
                self.descriptors[device] = fd
                self.identities[device] = identity
            except (OSError, KeyError, ValueError):
                if fd is not None:
                    os.close(fd)
                self.errors += 1
        self.scanned_at = now

    def coverage(self):
        return dict(input_eligible=self.eligible, input_opened=len(self.descriptors),
                    input_errors=self.errors, input_scan_at=self.scanned_at)


def read_snapshot(now=None):
    now = time.monotonic() if now is None else now
    try:
        value = json.loads(STATE.read_text())
        if value.get('boot_id') != BOOT.read_text().strip():
            return None
        for key in ('observed_at', 'physical_input_at', 'video_at'):
            n = value[key]
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n < 0 or n > now + 1:
                return None
        if not 0 <= now - value['observed_at'] <= FRESH_SECONDS:
            return None
        return value
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def video_health(record, now=None):
    """True/False from packet activity, None when the observer is unavailable."""
    now = time.monotonic() if now is None else now
    snapshot = read_snapshot(now)
    if snapshot is None or snapshot.get('video_port',47998) != record.get('video_port',47998):
        return None
    return (snapshot['video_at'] > 0 and
            snapshot['video_at'] >= record.get('started_monotonic', now) and
            now - snapshot['video_at'] <= VIDEO_SECONDS)


def physical_device(path):
    # Exclude uinput devices (including Sunshine's passthrough). Bluetooth UHID
    # lives below virtual/misc/uhid, so it is not excluded by this exact prefix.
    try:
        return '/devices/virtual/input/' not in str(path.resolve())
    except OSError:
        return False


def is_activity(kind, code, value):
    return ((kind == 1 and value in (1, 2)) or
            (kind == 2 and code in (0, 1, 6, 8) and value != 0) or
            (kind == 3 and code in (0, 1, 53, 54)))


def serve(output=STATE, video_port=47998):
    if type(video_port) is not int or not 1 <= video_port <= 65535:
        raise ValueError("Invalid video port")
    selector = selectors.DefaultSelector()
    # tcpdump's kernel filter selects only outgoing video-port packets. The
    # textual metadata is immediately discarded, never logged or persisted.
    network = subprocess.Popen(
        ['/usr/bin/tcpdump', '-p', '-i', 'any', '-Q', 'out', '-n', '-l', '-q',
         '-s', '64', '-Z', 'tcpdump', f'udp src port {video_port}'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    os.set_blocking(network.stdout.fileno(), False)
    selector.register(network.stdout, selectors.EVENT_READ, 'video')
    inputs = InputDevices(selector)
    boot = BOOT.read_text().strip()
    previous = read_snapshot()
    last_input = previous['physical_input_at'] if previous else 0.
    last_video = 0.
    producer_identity = dict(schema=SCHEMA, instance=uuid.uuid4().hex, producer_pid=os.getpid(), source_sha256=source_hash(),
                    producer_started_at=time.monotonic(), video_port=video_port)
    scan_at = write_at = 0.
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopped:
            now = time.monotonic()
            if network.poll() is not None:
                raise RuntimeError('Video observer exited')
            if now >= scan_at:
                inputs.scan(now)
                scan_at = now + 2
            for key, _ in selector.select(.25):
                try:
                    data = os.read(key.fd, 65536 if key.data == 'video' else EVENT.size * 64)
                    if not data:
                        raise OSError('Observer input closed')
                    if key.data == 'video':
                        last_video = time.monotonic()
                    else:
                        for start in range(0, len(data) - EVENT.size + 1, EVENT.size):
                            _, _, kind, code, value = EVENT.unpack_from(data, start)
                            if not is_activity(kind, code, value):
                                continue
                            if kind == 3:
                                identity = (key.fd, code)
                                previous = inputs.absolute.get(identity)
                                inputs.absolute[identity] = value
                                if previous is None or previous == value:
                                    continue
                            last_input = time.monotonic()
                except BlockingIOError:
                    pass
                except OSError:
                    if key.data == 'video':
                        raise
                    inputs.close(key.data)
                    inputs.errors += 1
            if now >= write_at:
                value = dict(boot_id=boot, observed_at=time.monotonic(),
                             physical_input_at=last_input, video_at=last_video,
                             **producer_identity, **inputs.coverage())
                temporary = output.with_suffix('.tmp')
                temporary.write_text(json.dumps(value))
                temporary.chmod(0o644)
                os.replace(temporary, output)
                write_at = now + .5
    finally:
        network.terminate()
        try:
            network.wait(timeout=3)
        except subprocess.TimeoutExpired:
            network.kill(); network.wait()
        for device in list(inputs.descriptors):
            inputs.close(device)
        selector.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=STATE)
    parser.add_argument('--video-port', type=int, default=int(os.environ.get('SDG_VIDEO_PORT', '47998')))
    args = parser.parse_args()
    serve(args.output,args.video_port)
