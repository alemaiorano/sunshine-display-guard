"""Failure injection at input access, async callbacks, and topology boundaries."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from test_sunshine_regressions import (Fixture, RestartPersistenceTests, policy, session,
                                      observer, row, input_snapshot)


class CallbackTests(Fixture):
    helper = RestartPersistenceTests.helper
    def configured_helper(self):
        h=self.helper();h.GLib=MagicMock();h.bus=MagicMock();h.dbus=MagicMock()
        h.dbus.DBusException=RuntimeError
        h.dbus.Interface.return_value.GetCurrentState.return_value=[None,None,[(0,0,1.,0,True,[['DP-3']])]]
        return h

    def test_async_config_write_holds_real_cross_process_lock(self):
        h=self.configured_helper();paths=MagicMock();paths.return_value.glob.return_value=['connected']
        config=paths.return_value.expanduser.return_value
        config.read_text.return_value='output_name = DP-4\n';config.stat.return_value.st_mode=0o100600
        observed=[]
        def write(*_):
            code='import fcntl,sys;f=open(sys.argv[1],"a");fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
            r=subprocess.run([sys.executable,'-c',code,str(session.LOCK)],capture_output=True)
            observed.append(r.returncode!=0)
        config.with_name.return_value.write_text.side_effect=write
        with patch.object(h,'Path',paths),patch.object(h.os,'replace'),patch.object(h,'request_restart'):
            h.sync_primary(True)
        self.assertEqual(observed,[True])

    def test_live_lease_defers_before_any_config_or_marker_write(self):
        h=self.configured_helper()
        with patch.object(h,'read_lease',return_value={'token':'owner'}),patch.object(h,'lease_alive',return_value=True),patch.object(h,'sync_primary_locked') as mutate,patch.object(h,'mark_restart_pending') as marker:
            h.sync_primary(True);h.sync_primary()
        mutate.assert_not_called();marker.assert_not_called()
        h.GLib.timeout_add_seconds.assert_called_once();self.assertTrue(h.sync_force)

    def test_no_hook_video_also_defers_config(self):
        h=self.configured_helper();h.read_snapshot.return_value={'video_at':policy.time.monotonic()}
        with patch.object(h,'sync_primary_locked') as mutate:
            h.sync_primary(True)
        mutate.assert_not_called()

    def test_busy_lock_is_bounded_and_keeps_force_until_retry(self):
        h=self.configured_helper()
        with patch.object(h,'lease_lock',side_effect=TimeoutError):h.sync_primary(True)
        with patch.object(h,'sync_primary_locked') as mutate:
            h.retry_sync();mutate.assert_called_once_with(True)
        self.assertFalse(h.sync_force)


class CoverageTests(Fixture):
    def test_healthy_zero_devices_is_legitimate_headless(self):
        self.assertEqual(observer.input_health(input_snapshot(0,100,input_eligible=0,input_opened=0),101),'no_devices')
    def test_partial_coverage_is_degraded_even_with_open_devices(self):
        self.assertEqual(observer.input_health(input_snapshot(0,100,input_eligible=2,input_opened=1,input_errors=1),101),'degraded')
    def test_legacy_or_missing_metadata_is_unknown(self):
        self.assertEqual(observer.input_health({'physical_input_at':0},100),'unknown')
    def test_stale_future_bool_and_nonfinite_coverage_is_not_healthy(self):
        for changes in [dict(input_scan_at=90),dict(input_scan_at=102),dict(input_scan_at=True),dict(input_scan_at=float('nan')),dict(input_opened=True),dict(input_opened=2)]:
            self.assertEqual(observer.input_health(input_snapshot(0,100,**changes),101),'degraded')
    def test_access_failure_uses_idle_fallback_instead_of_trusting_heartbeat(self):
        self.display([row('DP-1')]);p=policy.Policy(self.idle)
        now=policy.time.monotonic();p.last_tick=now-1;p.last_idle=60000
        self.idle.GetIdletime.return_value=20
        policy.read_snapshot.return_value=input_snapshot(0,input_opened=0,input_errors=1)
        with patch.object(p,'restore_physical') as restore:p.tick();restore.assert_called_once()
        self.assertTrue(p.observer_warning)
    def test_partial_coverage_still_latches_observed_event(self):
        self.display([row('DP-1')]);p=policy.Policy(self.idle);p.input_seen=0
        policy.read_snapshot.return_value=input_snapshot(policy.time.monotonic(),input_eligible=2,input_errors=1)
        with patch.object(p,'restore_physical') as restore:p.tick();restore.assert_called_once()


class InputAccessTests(unittest.TestCase):
    def setUp(self):
        self.selector=MagicMock();self.devices=observer.InputDevices(self.selector)
        self.device=Path('/dev/input/event99');self.stat=types.SimpleNamespace(st_ino=10,st_rdev=99)
    def scan(self,paths=None,opener=None):
        with patch.object(observer.Path,'glob',return_value=[Path('/sys/class/input/event99')] if paths is None else paths),patch.object(observer,'physical_device',return_value=True),patch.object(observer.Path,'stat',return_value=self.stat),patch.object(observer.os,'open',opener or MagicMock(return_value=71)),patch.object(observer.os,'fstat',return_value=self.stat),patch.object(observer.os,'close') as close:
            self.devices.scan(100)
        return close
    def test_open_permission_failure_is_published(self):
        self.scan(opener=MagicMock(side_effect=PermissionError()))
        self.assertEqual(self.devices.coverage(),dict(input_eligible=1,input_opened=0,input_errors=1,input_scan_at=100))
    def test_registration_failure_closes_opened_fd(self):
        self.selector.register.side_effect=OSError()
        close=self.scan();close.assert_called_once_with(71)
        self.assertEqual(self.devices.errors,1)
    def test_unplug_closes_fd_and_removes_absolute_cache(self):
        self.scan();self.devices.absolute={(71,0):5}
        close=self.scan(paths=[]);close.assert_called_once_with(71)
        self.assertEqual(self.devices.absolute,{})
        self.assertEqual(observer.input_health(dict(schema=2,**self.devices.coverage()),101),'no_devices')
    def test_replaced_event_node_is_reopened(self):
        self.scan();self.stat=types.SimpleNamespace(st_ino=11,st_rdev=99)
        close=self.scan();close.assert_called_once_with(71)
        self.assertEqual(self.selector.register.call_count,2)
    def test_retry_recovers_permission_failure(self):
        self.scan(opener=MagicMock(side_effect=PermissionError()));self.scan()
        self.assertEqual(observer.input_health(dict(schema=2,**self.devices.coverage()),101),'ready')

    def test_absolute_input_does_not_corrupt_producer_identity_or_heartbeat(self):
        import tempfile
        import signal
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'activity.json'
            selector=MagicMock();network=MagicMock();network.poll.return_value=None
            network.stdout.fileno.return_value=50
            inputs=MagicMock();inputs.absolute={};inputs.descriptors={}
            inputs.coverage.return_value=dict(input_eligible=1,input_opened=1,input_errors=0,input_scan_at=observer.time.monotonic())
            handlers={}
            def select(*_):
                handlers[signal.SIGTERM]()
                return [(types.SimpleNamespace(fd=51,data=self.device),1)]
            selector.select.side_effect=select
            data=observer.EVENT.pack(0,0,3,0,10)+observer.EVENT.pack(0,0,3,0,11)
            with patch.object(observer.selectors,'DefaultSelector',return_value=selector),patch.object(observer.subprocess,'Popen',return_value=network),patch.object(observer.os,'set_blocking'),patch.object(observer.os,'read',return_value=data),patch.object(observer.signal,'signal',side_effect=lambda kind,fn:handlers.update({kind:fn})),patch.object(observer,'InputDevices',return_value=inputs),patch.object(observer,'read_snapshot',return_value=None):
                observer.serve(output)
            value=json.loads(output.read_text())
            self.assertEqual(value['producer_pid'],os.getpid())
            self.assertGreater(value['physical_input_at'],0)
            self.assertEqual(value['source_sha256'],observer.source_hash())
            self.assertEqual(len(value['instance']),32)


class OneAndZeroMonitorTests(Fixture):
    def test_only_each_physical_connector_restores_without_other_monitor(self):
        for connector in ['DP-3','DP-4']:
            with self.subTest(connector=connector):
                d=self.display([row('DP-1')]);d.modes={c:m for c,m in d.modes.items() if c in ('DP-1',connector)}
                p=policy.Policy(self.idle);p.pending_return=True;p.tick()
                self.assertEqual([m[0] for r in d.layout for m in r[-1]],[connector])
                self.assertFalse(p.pending_return)
    def test_no_physical_monitor_keeps_reserve_despite_input(self):
        d=self.display([row('DP-1')]);d.modes={'DP-1':d.modes['DP-1']}
        p=policy.Policy(self.idle);p.pending_return=True;p.tick()
        self.assertEqual(d.layout,[row('DP-1')]);self.assertEqual(d.calls,[])
    def test_one_monitor_without_reserve_still_wakes_and_syncs(self):
        d=self.display([row('DP-3')]);d.modes={'DP-3':d.modes['DP-3']}
        policy.Policy(self.idle).tick();policy.helper.wake.assert_called_once();policy.helper.sync_primary.assert_called_once()
    def test_hot_unplug_last_physical_preserves_virtual_capture(self):
        d=self.display([row('DP-3')]);d.modes={'DP-1':d.modes['DP-1']}
        policy.Policy(self.idle).tick();self.assertEqual(d.primary,'DP-1')
    def test_no_outputs_retries_without_crashing_or_claiming_success(self):
        d=self.display([]);d.modes={}
        self.assertTrue(policy.Policy(self.idle).tick());policy.helper.wake.assert_called_once()


del RestartPersistenceTests  # imported test class is a helper, not another suite
