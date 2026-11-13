"""Exercise policy state transitions without touching live displays."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from sunshine_layout import normalize_layout
spec=importlib.util.spec_from_file_location('desktop_policy',ROOT/'scripts/sunshine-desktop-policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


def mode(name='1080p',w=1920,h=1080,scale=(1.,1.25,2.)):
    return (name,w,h,60.,1.,scale,{'is-preferred':True})


def row(c='DP-4',primary=True,x=0,y=0,transform=0):
    return (x,y,1.,transform,primary,[(c,'1080p',{})])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.d=MagicMock();self.d.modes={c:[mode()] for c in ['DP-1','DP-3','DP-4']}
        self.d.options={'layout-mode':1};self.d.layout=[row('DP-1')];self.d.primary='DP-1';self.d.power.return_value=0
        self.idle=MagicMock();self.idle.GetIdletime.return_value=10000
        self.p=policy.Policy(self.idle)
        self.file=MagicMock();self.file.exists.return_value=True;self.file.read_text.return_value='[]'
        for name,value in [('Display',MagicMock(return_value=self.d)),('RESERVE','DP-1'),
            ('LAYOUT',self.file),('read_lease',MagicMock(return_value=None)),('lease_lock',MagicMock()),
            ('other_stream_active',MagicMock(return_value=False)),('atomic_json',MagicMock()),
            ('helper',MagicMock()),('read_snapshot',MagicMock(return_value=None))]:
            patcher=patch.object(policy,name,value);patcher.start();self.addCleanup(patcher.stop)

    def test_headless_keeps_virtual(self):
        self.d.modes={'DP-1':[mode()]};self.p.tick()
        self.d.only.assert_not_called();self.d.apply.assert_not_called()

    def test_mirror_with_virtual_first(self):
        members=[('DP-1','1080p',{}),('DP-3','1080p',{}),('DP-4','1080p',{})]
        self.d.layout=[(0,0,1.,0,True,members)]
        self.d.primary='DP-1'
        self.p.tick()
        self.d.apply.assert_called_once_with([(0,0,1.,0,True,members[1:])])

    def test_join_with_portrait_unchanged(self):
        self.d.layout=[row('DP-4'),row('DP-3',False,1920,0,1)];self.d.primary='DP-4'
        self.p.tick();self.d.apply.assert_not_called()

    def test_small_idle_reset_is_activity(self):
        self.p.last_idle=900;self.p.last_tick=0
        self.idle.GetIdletime.return_value=0
        with patch.object(policy.time,'monotonic',return_value=1),patch.object(self.p,'restore_physical') as restore:
            self.p.tick();restore.assert_called_once()

    def test_continuous_activity_is_detected(self):
        self.p.last_idle=0;self.p.last_tick=0;self.idle.GetIdletime.return_value=0
        with patch.object(policy.time,'monotonic',return_value=1),patch.object(self.p,'restore_physical') as restore:
            self.p.tick();restore.assert_called_once()

    def test_idle_growing_does_not_restore(self):
        self.p.last_idle=10000;self.p.last_tick=0;self.idle.GetIdletime.return_value=11000
        with patch.object(policy.time,'monotonic',return_value=1):self.p.tick()
        self.d.only.assert_not_called();self.d.apply.assert_not_called()

    def test_pending_input_survives_live_session(self):
        policy.read_lease.return_value={'token':'a'}
        self.p.pending_return=True
        with patch.object(policy,'lease_alive',return_value=True):self.p.tick()
        self.assertTrue(self.p.pending_return);self.d.apply.assert_not_called()

    def test_orphan_recovery_is_attempted(self):
        policy.read_lease.return_value={'token':'a'}
        with patch.object(policy,'lease_alive',return_value=False),patch.object(policy,'restore',return_value=True) as restore:
            self.p.tick();restore.assert_called_once_with('a',locked=True)

    def test_poisoned_primary_repaired_before_apply(self):
        self.file.read_text.return_value=json.dumps([row('DP-3'),row('DP-4',True,1920)])
        confirmed=MagicMock();confirmed.options={"layout-mode":1};confirmed.modes=self.d.modes
        confirmed.layout=[row('DP-3'),row('DP-4',False,1920)];confirmed.primary='DP-3'
        policy.Display.return_value=confirmed
        self.p.restore_physical(self.d)
        applied=self.d.apply.call_args.args[0]
        self.assertEqual(sum(r[4] for r in applied),1)
        self.assertFalse(self.p.pending_return)

    def test_corrupt_layout_tries_other_physical_screen(self):
        self.file.read_text.return_value='invalid'
        self.d.only.side_effect=[ValueError('broken connector'),None]
        confirmed=MagicMock();confirmed.options={"layout-mode":1};confirmed.modes=self.d.modes;confirmed.layout=[row('DP-4')];confirmed.primary='DP-4'
        policy.Display.return_value=confirmed
        self.p.restore_physical(self.d)
        self.assertEqual(self.d.only.call_count,2)

    def test_failed_confirmation_keeps_pending(self):
        self.p.pending_return=True
        with self.assertRaises(ValueError):self.p.restore_physical(self.d)
        self.assertTrue(self.p.pending_return)

    def test_sleep_saves_layout_before_reserve(self):
        self.d.layout=[row('DP-4')];self.d.primary='DP-4';self.d.power.return_value=1
        self.p.tick();self.d.only.assert_called_once()
        self.assertEqual(policy.atomic_json.call_args.args[1],[row('DP-4')])

    def test_compositor_idle_reset_does_not_request_return(self):
        self.p.last_idle=60000;self.p.last_tick=0.;self.p.activity_after=.5
        self.idle.GetIdletime.return_value=950
        snapshot=dict(physical_input_at=0,schema=2,input_eligible=1,input_opened=1,input_errors=0,input_scan_at=1.)
        with patch.object(policy.time,'monotonic',return_value=1.),patch.object(policy,'read_snapshot',return_value=snapshot),patch.object(self.p,'restore_physical') as restore:
            self.p.tick();restore.assert_not_called()
    def test_input_after_compositor_settles_requests_return(self):
        self.p.last_idle=950;self.p.last_tick=1.;self.p.activity_after=.5
        self.idle.GetIdletime.return_value=0
        with patch.object(policy.time,'monotonic',return_value=2.),patch.object(self.p,'restore_physical') as restore:
            self.p.tick();restore.assert_called_once()


class OtherStreamTests(unittest.TestCase):
    def run_query(self,stdout='',stderr='',code=0):
        result=MagicMock(returncode=code,stdout=stdout,stderr=stderr,args=['journalctl'])
        with patch.object(policy.subprocess,'check_output',return_value='invocation'),patch.object(policy.subprocess,'run',return_value=result):
            return policy.other_stream_active()
    def test_no_matching_logs_is_not_error(self):self.assertFalse(self.run_query(code=1))
    def test_query_permission_failure_is_not_idle(self):
        with self.assertRaises(policy.subprocess.CalledProcessError):self.run_query(stderr='permission denied',code=1)
    def test_restart_clears_stale_client_balance(self):
        self.assertFalse(self.run_query('Info: CLIENT CONNECTED\nInfo: Sunshine version: new\n'))
    def test_live_connection_is_protected(self):self.assertTrue(self.run_query('Info: CLIENT CONNECTED\n'))
    def test_disconnect_balance(self):
        self.assertFalse(self.run_query('Info: CLIENT CONNECTED\nInfo: CLIENT DISCONNECTED\n'))
