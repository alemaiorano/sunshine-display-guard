"""Regression witnesses for display ownership, recovery and input invariants.

Display inherits the real primary/mode/only contract. Only the hardware API
boundary is replaced, and the transaction is checked from another process.
"""
from dataclasses import replace
import copy
import importlib.util
import io
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
from gi.repository import Gio

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import sunshine_session_display as session
import sunshine_observer as observer
from sunshine_layout import atomic_json,normalize_layout
spec=importlib.util.spec_from_file_location('policy_regression',ROOT/'scripts/sunshine-desktop-policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
spec=importlib.util.spec_from_file_location('client_regression',ROOT/'scripts/moonlight-client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


def mode(name='hd',w=1920,h=1080):
    return (name,w,h,60.,1.,[1.],{'is-current':True,'is-preferred':True})


def row(connector,x=0,primary=True):
    return (x,0,1.,0,primary,[(connector,'hd',{})])


def input_snapshot(event, now=None, **values):
    value=dict(physical_input_at=event, video_at=0, schema=2, input_eligible=1,
               input_opened=1, input_errors=0,
               input_scan_at=time.monotonic() if now is None else now)
    value.update(values)
    return value


class Model(session.Display):
    def __init__(self,layout):
        self.layout=copy.deepcopy(layout)
        self.modes={c:[mode(),mode('portrait',1080,1920)] for c in ['DP-1','DP-3','DP-4']}
        self.options={'layout-mode':1};self.calls=[];self.power_value=0
    def apply(self,layout):
        self.calls.append(copy.deepcopy(layout));self.layout=normalize_layout(layout,self.modes)
    def power(self,enable=False):
        if enable:self.power_value=0
        return self.power_value


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.lease=self.folder/'lease.json'
        for name,value in [('RESERVE','DP-1'),('LEASE',self.lease),('LOCK',self.folder/'display.lock'),
                           ('CAPTURE_RESTART',self.folder/'restart.json')]:
            self.replace(session,name,value)
        self.replace(session,'invocation_id',lambda:'fixture')
        self.layout=self.folder/'layout.json'
        atomic_json(self.layout,[row('DP-3'),row('DP-4',1920,False)])
        self.replace(policy,'LAYOUT',self.layout)
        self.replace(policy,'RESERVE','DP-1')
        self.replace(policy,'helper',MagicMock())
        self.replace(policy,'read_snapshot',MagicMock(return_value=None))
        self.replace(policy,'other_stream_active',MagicMock(return_value=False))
        self.idle=MagicMock();self.idle.GetIdletime.return_value=10000
    def replace(self,target,name,value):
        p=patch.object(target,name,value);p.start();self.addCleanup(p.stop)
    def display(self,layout):
        d=Model(layout);self.replace(session,'Display',MagicMock(return_value=d))
        self.replace(policy,'Display',MagicMock(return_value=d));return d
    def record(self,**values):
        r=dict(token='fixture',invocation='fixture',started=time.time(),started_monotonic=time.monotonic())
        r.update(values);return r


class MirrorAndOwnershipTests(Fixture):
    def test_prepare_never_disables_members_of_mirror(self):
        mirror=[(0,0,1.,0,True,[('DP-1','hd',{}),('DP-3','hd',{}),('DP-4','hd',{})])]
        d=self.display(mirror)
        self.assertEqual(d.primary,'DP-1')
        with patch.dict(os.environ,SUNSHINE_CLIENT_WIDTH='1080',SUNSHINE_CLIENT_HEIGHT='1920'):
            session.prepare()
        self.assertEqual(d.layout,mirror);self.assertEqual(d.calls,[])
        self.assertNotIn('previous',session.read_lease())

    def test_mirror_order_and_input_never_restore_stale_extension(self):
        for order in itertools.permutations(['DP-1','DP-3','DP-4']):
            with self.subTest(order=order):
                d=self.display([(0,0,1.,0,True,[(c,'hd',{}) for c in order])])
                self.idle.GetIdletime.return_value=0
                policy.Policy(self.idle).tick()
                self.assertEqual(len(d.layout),1)
                self.assertEqual([m[0] for m in d.layout[0][-1]],[c for c in order if c!='DP-1'])

    def test_transaction_is_held_during_apply_and_stream_query(self):
        d=self.display([row('DP-1')]);p=policy.Policy(self.idle);p.pending_return=True
        code='''import fcntl,sys
with open(sys.argv[1], 'a') as f:
 try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError: sys.exit(73)
'''
        def query():
            result=subprocess.run([sys.executable,'-c',code,str(session.LOCK)],capture_output=True)
            self.assertEqual(result.returncode,73)
            self.assertFalse(self.lease.exists())
            return False
        policy.other_stream_active.side_effect=query
        p.tick()
        self.assertEqual(len(d.layout),2)
        self.assertEqual(subprocess.run([sys.executable,'-c',code,str(session.LOCK)],capture_output=True).returncode,0)
        # A no-op prepare can only acquire after the policy has finished.
        session.prepare();self.assertTrue(session.read_lease())
        self.assertEqual(len(d.layout),2)

    def test_prepare_winning_transaction_vetoes_policy_mutation(self):
        d=self.display([row('DP-1')])
        with patch.dict(os.environ,SUNSHINE_CLIENT_WIDTH='1920',SUNSHINE_CLIENT_HEIGHT='1080'):
            session.prepare()
        p=policy.Policy(self.idle);p.pending_return=True;p.tick()
        self.assertEqual(d.calls,[])

    def test_nested_transaction_is_reentrant(self):
        with session.lease_lock(timeout=0):
            with session.lease_lock(timeout=0):pass

    def test_busy_transaction_is_bounded(self):
        p=policy.Policy(self.idle)
        with patch.object(policy,'lease_lock',side_effect=TimeoutError('busy')):
            self.assertTrue(p.tick())

    def test_capture_pending_prevents_new_prepare(self):
        session.CAPTURE_RESTART.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'reconciliation'):
            session.prepare()

    def test_restore_does_not_overwrite_new_user_mirror(self):
        mirror=[(0,0,1.,0,True,[('DP-1','portrait',{}),('DP-3','hd',{})])]
        d=self.display(mirror)
        atomic_json(self.lease,self.record(connector='DP-1',previous='hd',target='portrait'))
        session.restore('fixture')
        self.assertEqual(d.layout,mirror)


class InputAndHealthTests(Fixture):
    def test_physical_key_during_settling_is_not_lost(self):
        self.display([row('DP-1')]);p=policy.Policy(self.idle)
        p.input_seen=0;p.activity_after=.5;p.last_tick=0;p.last_idle=60000
        policy.read_snapshot.return_value=input_snapshot(.4, 1.)
        self.idle.GetIdletime.return_value=600
        with patch.object(policy.time,'monotonic',return_value=1.),patch.object(p,'restore_physical') as restore:
            p.tick();restore.assert_called_once()

    def test_physical_key_wins_over_simultaneous_standby(self):
        d=self.display([row('DP-3'),row('DP-4',1920,False)]);d.power_value=1
        policy.read_snapshot.return_value=input_snapshot(time.monotonic())
        p=policy.Policy(self.idle);p.input_seen=0
        p.tick()
        self.assertEqual(d.power_value,0);self.assertEqual(d.calls,[])
        self.assertTrue(p.pending_return)
        p.tick();self.assertFalse(p.pending_return)
        self.assertEqual(len(d.layout),2)

    def test_no_physical_event_ignores_compositor_reset(self):
        d=self.display([row('DP-1')]);p=policy.Policy(self.idle)
        p.input_seen=0;p.last_tick=0;p.last_idle=60000
        self.idle.GetIdletime.return_value=0
        policy.read_snapshot.return_value=input_snapshot(0)
        p.tick();self.assertEqual(d.calls,[])

    def test_fallback_defers_but_latches_input_inside_window(self):
        self.display([row('DP-1')]);p=policy.Policy(self.idle)
        p.last_tick=0;p.last_idle=60000;p.activity_after=.5
        self.idle.GetIdletime.side_effect=[20,920]
        with patch.object(policy.time,'monotonic',side_effect=[.1,1.]),patch.object(p,'restore_physical') as restore:
            p.tick_locked();self.assertTrue(p.pending_return);restore.assert_not_called()
            p.tick_locked();restore.assert_called_once()

    def test_watcher_pid_alive_without_video_does_not_veto_forever(self):
        r=self.record(pid=123,process_start='1',started_monotonic=1.)
        with patch.object(session,'process_start',return_value='1'),patch.object(session,'video_health',return_value=False),patch.object(session.time,'monotonic',return_value=100.):
            self.assertFalse(session.lease_alive(r,'fixture'))

    def test_healthy_long_stream_is_not_expired_by_age(self):
        r=self.record(pid=123,process_start='1',started_monotonic=1.)
        with patch.object(session,'process_start',return_value='1'),patch.object(session,'video_health',return_value=True),patch.object(session.time,'monotonic',return_value=86400.):
            self.assertTrue(session.lease_alive(r,'fixture'))

    def test_observer_failure_has_bounded_grace(self):
        r=self.record(started_monotonic=1.,health_confirmed_monotonic=100.)
        with patch.object(session,'video_health',return_value=None):
            self.assertTrue(session.stream_alive(r,159.))
            self.assertFalse(session.stream_alive(r,161.))

    def test_observer_restart_preserves_only_recent_verified_video(self):
        r=self.record(started_monotonic=1.,health_confirmed_monotonic=100.)
        with patch.object(session,'video_health',return_value=False):
            self.assertTrue(session.stream_alive(r,110.))
            self.assertFalse(session.stream_alive(r,121.))

    def test_lost_disconnect_exits_by_packet_health(self):
        journal=MagicMock();journal.poll.side_effect=[None,None,0]
        selector=MagicMock();selector.select.side_effect=[[(None,None)]]
        r=self.record(started_monotonic=0.)
        with patch.object(session.subprocess,'Popen',return_value=MagicMock(__enter__=MagicMock(return_value=journal))),patch.object(session.selectors,'DefaultSelector',return_value=MagicMock(__enter__=MagicMock(return_value=selector))),patch.object(session.os,'read',return_value=b'Info: CLIENT CONNECTED\n'),patch.object(session.time,'monotonic',side_effect=[0.,1.,61.]),patch.object(session,'video_health',return_value=False):
            session.watch_session(r)
        self.assertEqual(selector.select.call_count,1)

    def test_lost_connect_log_does_not_kill_video_at_45_seconds(self):
        r=self.record(started_monotonic=0.);atomic_json(self.lease,r)
        journal=MagicMock();journal.poll.side_effect=[None,None,0,0]
        selector=MagicMock();selector.select.return_value=[]
        with patch.object(session.subprocess,'Popen',return_value=MagicMock(__enter__=MagicMock(return_value=journal))),patch.object(session.selectors,'DefaultSelector',return_value=MagicMock(__enter__=MagicMock(return_value=selector))),patch.object(session.time,'monotonic',side_effect=[0.,1.,50.,51.]),patch.object(session,'stream_alive',side_effect=[True,True,False]),patch.object(session,'lease_lock',MagicMock()),patch.object(session,'video_health',return_value=True):
            session.watch_session(r)
        self.assertEqual(selector.select.call_count,2)

    def test_stopped_owned_journal_is_killed_after_bounded_wait(self):
        r=self.record(started_monotonic=0.)
        journal=MagicMock();journal.poll.side_effect=[None,None]
        journal.wait.side_effect=[subprocess.TimeoutExpired('journalctl',2),0]
        selector=MagicMock()
        with patch.object(session.subprocess,'Popen',return_value=MagicMock(__enter__=MagicMock(return_value=journal))),patch.object(session.selectors,'DefaultSelector',return_value=MagicMock(__enter__=MagicMock(return_value=selector))),patch.object(session.time,'monotonic',side_effect=[0.,61.]),patch.object(session,'video_health',return_value=False):
            session.watch_session(r)
        journal.terminate.assert_called_once();journal.kill.assert_called_once()


class SchemaTests(Fixture):
    def test_semantically_invalid_json_is_quarantined(self):
        for pid in [1e309,True,0,-1,'123',[],{},None]:
            with self.subTest(pid=str(pid)):
                value=self.record(pid=pid,process_start='1')
                self.lease.write_text(json.dumps(value))
                self.assertIsNone(session.read_lease())
                self.assertFalse(self.lease.exists())
        self.assertEqual(len(list(self.folder.glob('*.invalid-*.json'))),8)

    def test_corrupt_numeric_or_status_fields_are_rejected(self):
        for changes in [{'started':float('nan')},{'started_monotonic':float('inf')},{'attempts':'1'},{'status':'unknown'},{'token':[]},{'previous':'old'}]:
            with self.subTest(changes=changes):self.assertFalse(session.valid_lease(self.record(**changes)))

    def test_process_start_handles_overflow_without_crash(self):
        self.assertIsNone(session.process_start(float('inf')))


class ClientRequeryTests(Fixture):
    def state(self,w,h,transform=0):
        spec=('DP-4','brand','model','serial')
        return (1,[(spec,[mode('current',w,h)],{})],[(0,0,1.,transform,True,[spec],{})],{})
    def test_state_is_refreshed_after_selection(self):
        proxy=MagicMock();proxy.call_sync.side_effect=[MagicMock(unpack=MagicMock(return_value=self.state(1920,1080))),MagicMock(unpack=MagicMock(return_value=self.state(2560,1080,1)))]
        config=self.folder/'client.conf';config.write_text('[General]\nfps=60\nbitrate=20000\n')
        output=io.StringIO()
        with patch.object(sys,'argv',['client','--monitor','DP-4','--dry-run']),patch.object(Gio.DBusProxy,'new_for_bus_sync',return_value=proxy),patch.object(client,'SETTINGS',replace(client.SETTINGS,moonlight_host='host.example',resolution_fps_limits={'1080x2560':50})),patch('sys.stdout',output):
            client.main()
        command=json.loads(output.getvalue())['command']
        self.assertEqual(proxy.call_sync.call_count,2)
        self.assertEqual(command[command.index('--resolution')+1],'1080x2560')
        self.assertEqual(command[command.index('--fps')+1],'50')

    def test_detach_during_selection_does_not_launch_stale_target(self):
        proxy=MagicMock();proxy.call_sync.side_effect=[MagicMock(unpack=MagicMock(return_value=self.state(1920,1080))),MagicMock(unpack=MagicMock(return_value=(2,[],[],{})))]
        with patch.object(sys,'argv',['client','--monitor','DP-4','--dry-run']),patch.object(Gio.DBusProxy,'new_for_bus_sync',return_value=proxy):
            with self.assertRaisesRegex(ValueError,'disconnected'):client.main()


class ObserverTests(Fixture):
    def test_fresh_snapshot_validates_boot_and_finite_timestamps(self):
        state=self.folder/'activity.json';boot=self.folder/'boot';boot.write_text('boot')
        value=dict(boot_id='boot',observed_at=100.,physical_input_at=99.,video_at=98.)
        with patch.object(observer,'STATE',state),patch.object(observer,'BOOT',boot):
            atomic_json(state,value);self.assertIsNotNone(observer.read_snapshot(101.))
            self.assertIsNone(observer.read_snapshot(106.))
            value['physical_input_at']=float('inf');atomic_json(state,value)
            self.assertIsNone(observer.read_snapshot(101.))
            value['physical_input_at']=99.;value['boot_id']='old';atomic_json(state,value)
            self.assertIsNone(observer.read_snapshot(101.))

    def test_virtual_input_excluded_bluetooth_and_usb_preserved(self):
        for path,expected in [('/sys/devices/virtual/input/input1',False),('/sys/devices/virtual/misc/uhid/1/input/input1',True),('/sys/devices/pci0000/usb/input/input1',True)]:
            mock=MagicMock();mock.resolve.return_value=Path(path)
            self.assertEqual(observer.physical_device(mock),expected)

    def test_activity_classification(self):
        self.assertTrue(observer.is_activity(1,30,1));self.assertTrue(observer.is_activity(2,0,1))
        self.assertFalse(observer.is_activity(1,30,0));self.assertFalse(observer.is_activity(2,0,0))
        self.assertFalse(observer.is_activity(0,0,0))

class RestartPersistenceTests(Fixture):
    def helper(self):
        spec=importlib.util.spec_from_file_location('restart_fresh',ROOT/'scripts/keep-display-awake.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        helper.RESTART_STATE=session.CAPTURE_RESTART
        helper.SETTINGS=replace(helper.SETTINGS,follow_primary=True,restart_credentials='fixture')
        helper.read_snapshot=MagicMock(return_value=None)
        return helper

    def test_pending_intent_survives_fresh_helper_process_state(self):
        first=self.helper();first.mark_restart_pending('DP-4')
        fresh=self.helper();self.assertFalse(fresh.restart_pending)
        self.assertTrue(fresh.restart_is_pending())
        paths=MagicMock();paths.return_value.glob.return_value=['connected']
        paths.return_value.expanduser.return_value.read_text.return_value='output_name = DP-4\n'
        dbus=MagicMock();dbus.DBusException=RuntimeError
        dbus.Interface.return_value.GetCurrentState.return_value=[None,None,[(0,0,1.,0,True,[['DP-4']])]]
        with patch.object(fresh,'Path',paths),patch.object(fresh,'bus',MagicMock(),create=True),patch.object(fresh,'dbus',dbus,create=True),patch.object(fresh,'request_restart') as restart:
            fresh.sync_primary();restart.assert_called_once()

    def test_api_retry_holds_same_transaction(self):
        helper=self.helper()
        code='''import fcntl,sys
with open(sys.argv[1], 'a') as f:
 try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
 except BlockingIOError: sys.exit(73)
'''
        def api(*_):
            result=subprocess.run([sys.executable,'-c',code,str(session.LOCK)],capture_output=True)
            self.assertEqual(result.returncode,73);return False
        with patch.object(helper,'read_snapshot',return_value=None),patch.object(helper,'restart_sunshine_locked',side_effect=api) as action:
            helper.restart_sunshine();action.assert_called_once()

    def test_retry_defers_while_new_session_owns_display(self):
        helper=self.helper();atomic_json(self.lease,self.record())
        with patch.object(helper,'read_snapshot',return_value=None),patch.object(helper,'GLib',MagicMock(),create=True),patch.object(helper,'restart_sunshine_locked') as action:
            helper.restart_sunshine();action.assert_not_called()
        self.assertTrue(session.CAPTURE_RESTART.exists())

    def test_retry_defers_for_video_without_session_hooks(self):
        helper=self.helper()
        with patch.object(helper,'read_snapshot',return_value={'video_at':time.monotonic()}),patch.object(helper,'GLib',MagicMock(),create=True),patch.object(helper,'restart_sunshine_locked') as action:
            helper.restart_sunshine();action.assert_not_called()
        self.assertTrue(session.CAPTURE_RESTART.exists())
