"""Remote-only topology must be explicit, transactional and reversible."""
import copy
from dataclasses import replace
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch
from test_sunshine_regressions import Fixture, row, session


def observer_snapshot(video_at=0, **changes):
    data=dict(video_at=video_at, schema=2, video_port=session.SETTINGS.video_port,
              source_sha256=session.observer_source_hash())
    data.update(changes);return data


class RemoteDesktopTests(Fixture):
    def setUp(self):
        super().setUp()
        self.replace(session, 'require_remote_idle', lambda invocation: None)
        p=patch.dict(os.environ, SUNSHINE_CLIENT_WIDTH='1080',
                     SUNSHINE_CLIENT_HEIGHT='1920', SUNSHINE_CLIENT_FPS='60')
        p.start();self.addCleanup(p.stop)

    def test_extension_round_trip_persists_before_mutation(self):
        d=self.display([row('DP-3'), row('DP-4',1920,False)])
        original=copy.deepcopy(d.layout)
        apply=d.apply
        def verify(layout):
            saved=session.read_lease()
            self.assertEqual(saved['previous_layout'],json.loads(json.dumps(original)))
            return apply(layout)
        d.apply=verify
        session.prepare(remote=True)
        r=session.read_lease()
        self.assertTrue(r['remote_exclusive']);self.assertEqual(d.layout[0][-1][0][0],'DP-1')
        self.assertEqual(d.layout[0][-1][0][1],'portrait')
        d.apply=apply
        session.restore(r['token'])
        self.assertEqual(d.layout,original)
        self.assertIsNone(session.read_lease())

    def test_mirror_can_be_explicitly_replaced_and_restored(self):
        original=[(0,0,1.,0,True,[('DP-1','hd',{}),('DP-3','hd',{})])]
        d=self.display(original)
        session.prepare(remote=True);self.assertEqual(len(d.layout[0][-1]),1)
        session.restore(session.read_lease()['token']);self.assertEqual(d.layout,original)

    def test_failed_activation_aborts_and_does_not_silently_stream_physical(self):
        d=self.display([row('DP-3')]);d.only=lambda *a:None
        with self.assertRaisesRegex(ValueError,'not confirmed'):session.prepare(remote=True)
        self.assertEqual(d.layout,[row('DP-3')]);self.assertIsNone(session.read_lease())

    def test_new_manual_layout_survives_disconnect(self):
        d=self.display([row('DP-3')]);session.prepare(remote=True);token=session.read_lease()['token']
        d.layout=[row('DP-4')];session.restore(token);self.assertEqual(d.layout,[row('DP-4')])

    def test_invalid_dimensions_never_mutate_or_leave_lease(self):
        d=self.display([row('DP-3')])
        with patch.dict(os.environ,SUNSHINE_CLIENT_WIDTH='0'):
            with self.assertRaises(ValueError):session.prepare(remote=True)
        self.assertEqual(d.calls,[]);self.assertFalse(self.lease.exists())

    def test_failed_apply_restores_mutation_before_propagating(self):
        d=self.display([row('DP-3')]);original=copy.deepcopy(d.layout);apply=d.only
        def partial(*args):
            apply(*args);raise ValueError('late compositor failure')
        d.only=partial
        with self.assertRaisesRegex(ValueError,'late compositor'):session.prepare(remote=True)
        self.assertEqual(d.layout,original);self.assertFalse(self.lease.exists())


class RemoteIdleTests(unittest.TestCase):
    def test_recent_video_refuses(self):
        with patch.object(session,'read_activity',return_value=observer_snapshot(time.monotonic())):
            with self.assertRaisesRegex(RuntimeError,'Video active'):session.require_remote_idle('test')
    def test_missing_observer_refuses(self):
        with patch.object(session,'read_activity',return_value=None):
            with self.assertRaises(RuntimeError):session.require_remote_idle('test')
    def test_connected_silent_client_refuses(self):
        result=subprocess.CompletedProcess([],0,'Info: CLIENT CONNECTED\n','')
        with patch.object(session,'read_activity',return_value=observer_snapshot()),patch.object(session.subprocess,'run',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'Another client'):session.require_remote_idle('test')
    def test_unreadable_journal_refuses(self):
        result=subprocess.CompletedProcess([],1,'','Permission denied')
        with patch.object(session,'read_activity',return_value=observer_snapshot()),patch.object(session.subprocess,'run',return_value=result):
            with self.assertRaises(RuntimeError):session.require_remote_idle('test')
    def test_journal_warning_even_with_success_status_refuses(self):
        result=subprocess.CompletedProcess([],0,'','Some journal files could not be opened')
        with patch.object(session,'read_activity',return_value=observer_snapshot()),patch.object(session.subprocess,'run',return_value=result):
            with self.assertRaises(RuntimeError):session.require_remote_idle('test')
    def test_disconnected_client_allows(self):
        result=subprocess.CompletedProcess([],0,'Info: CLIENT CONNECTED\nInfo: CLIENT DISCONNECTED\n','')
        with patch.object(session,'read_activity',return_value=observer_snapshot()),patch.object(session.subprocess,'run',return_value=result):
            session.require_remote_idle('test')

class GenericRemoteTests(Fixture):
    def setUp(self):
        super().setUp()
        self.replace(session,'require_remote_idle',lambda invocation:None)
        p=patch.dict(os.environ,SUNSHINE_CLIENT_WIDTH='1080',SUNSHINE_CLIENT_HEIGHT='1920',SUNSHINE_CLIENT_FPS='120')
        p.start();self.addCleanup(p.stop)

    def test_single_physical_round_trip(self):
        d=self.display([row('DP-3')]);original=copy.deepcopy(d.layout)
        session.prepare(remote=True);session.restore(session.read_lease()['token'])
        self.assertEqual(d.layout,original)

    def test_reserve_only_round_trip(self):
        d=self.display([row('DP-1')]);original=copy.deepcopy(d.layout)
        session.prepare(remote=True);session.restore(session.read_lease()['token'])
        self.assertEqual(d.layout,original)

    def test_missing_reserve_does_not_mutate(self):
        d=self.display([row('DP-3')]);del d.modes['DP-1']
        with self.assertRaises(KeyError):session.prepare(remote=True)
        self.assertEqual(d.calls,[]);self.assertFalse(self.lease.exists())

    def test_observer_gate_precedes_stale_lease_restore(self):
        atomic={'started':time.time()-120,'started_monotonic':time.monotonic()-120,'token':'old','invocation':'fixture'}
        self.lease.write_text(json.dumps(atomic));d=self.display([row('DP-3')])
        with patch.object(session,'require_remote_idle',side_effect=RuntimeError('busy')),patch.object(session,'restore') as restore:
            with self.assertRaisesRegex(RuntimeError,'busy'):session.prepare(remote=True)
            restore.assert_not_called()
        self.assertEqual(d.calls,[])

    def test_lease_uses_configured_port_and_unclamped_public_fps(self):
        d=self.display([row('DP-3')]);called=[];original=d.mode
        def mode(connector,size=None,fps=60):
            called.append(fps);return original(connector,size,fps)
        d.mode=mode
        with patch.object(session,'SETTINGS',replace(session.SETTINGS,video_port=50098)):
            session.prepare(remote=True)
        self.assertEqual(session.read_lease()['video_port'],50098)
        self.assertIn(120,called)


class GenericIdleTests(unittest.TestCase):
    def test_wrong_observer_port_or_source_refuses(self):
        for change in [dict(video_port=1),dict(source_sha256='wrong'),dict(schema=1)]:
            with self.subTest(change=change),patch.object(session,'read_activity',return_value=observer_snapshot(**change)):
                with self.assertRaises(RuntimeError):session.require_remote_idle('invocation')

    def test_matching_nondefault_port_and_service_scope(self):
        for scope,flag in [('user','--user-unit'),('system','--unit')]:
            settings=replace(session.SETTINGS,video_port=50098,sunshine_scope=scope)
            with self.subTest(scope=scope),patch.object(session,'SETTINGS',settings),patch.object(session,'read_activity',return_value=observer_snapshot(video_port=50098)),patch.object(session.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','')) as run:
                session.require_remote_idle('invocation')
                args=run.call_args.args[0]
                self.assertIn(flag,args);self.assertIn('_SYSTEMD_INVOCATION_ID=invocation',args)

    def test_remote_marker_schema_requires_rollback(self):
        value=dict(token='test',invocation='test',started=time.time(),remote_exclusive=True)
        self.assertFalse(session.valid_lease(value))
        value['remote_exclusive']='true';self.assertFalse(session.valid_lease(value))
