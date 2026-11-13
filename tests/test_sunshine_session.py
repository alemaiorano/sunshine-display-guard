import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import sunshine_session_display as session
from sunshine_layout import atomic_json

class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.file=Path(self.temp.name)/'lease.json'
        for name,value in [('RESERVE','DP-1'),('LEASE',self.file),('LOCK',self.file.with_suffix('.lock')),('CAPTURE_RESTART',self.file.with_suffix('.capture'))]:
            p=patch.object(session,name,value);p.start();self.addCleanup(p.stop)
    def record(self,**kwargs):
        kwargs.setdefault('started_monotonic',time.monotonic())
        return dict(started=time.time(),invocation='a',token='token',**kwargs)
    def test_missing_owner_invalid(self):self.assertFalse(session.lease_alive({},'a'))
    def test_different_invocation_invalid(self):self.assertFalse(session.lease_alive(self.record(),'b'))
    def test_prepared_grace_valid(self):self.assertTrue(session.lease_alive(self.record(),'a'))
    def test_old_prepared_invalid(self):
        r=self.record();r['started_monotonic']-=61;self.assertFalse(session.lease_alive(r,'a'))
    def test_future_invalid(self):
        r=self.record();r['started_monotonic']+=60;self.assertFalse(session.lease_alive(r,'a'))
    def test_dead_process_invalid(self):
        with patch.object(session,'process_start',return_value=None):
            self.assertFalse(session.lease_alive(self.record(pid=123,process_start='1'),'a'))
    def test_reused_pid_invalid(self):
        with patch.object(session,'process_start',return_value='2'):
            self.assertFalse(session.lease_alive(self.record(pid=123,process_start='1'),'a'))
    def test_live_owner_valid(self):
        with patch.object(session,'process_start',return_value='1'):
            self.assertTrue(session.lease_alive(self.record(pid=123,process_start='1'),'a'))
    def test_restoring_not_active(self):self.assertFalse(session.lease_alive(self.record(status='restoring'),'a'))
    def test_corrupt_json_quarantined(self):
        self.file.write_text('{');self.assertIsNone(session.read_lease())
        self.assertTrue(list(self.file.parent.glob('*.invalid-*.json')))
    def test_non_object_quarantined(self):
        self.file.write_text('[]');self.assertIsNone(session.read_lease())
    def test_other_token_cannot_restore(self):
        atomic_json(self.file,self.record());session.restore('other');self.assertTrue(self.file.exists())
    def test_failed_restore_preserves_then_quarantines(self):
        atomic_json(self.file,self.record(previous='old',target='new',connector='DP-1'))
        display=MagicMock();display.primary='DP-1';display.layout=[(0,0,1.,0,True,[('DP-1','new',{})])]
        display.apply.side_effect=ValueError('transient')
        with patch.object(session,'Display',return_value=display):
            for _ in range(3):self.assertFalse(session.restore('token'))
            self.assertTrue(self.file.exists());self.assertTrue(session.restore('token'))
        self.assertFalse(self.file.exists());self.assertTrue(self.file.with_suffix('.recovery.json').exists())
    def test_user_mode_change_is_preserved(self):
        atomic_json(self.file,self.record(previous='old',target='new',connector='DP-1'))
        display=MagicMock();display.primary='DP-1';display.layout=[(0,0,1.,0,True,[('DP-1','user',{})])]
        with patch.object(session,'Display',return_value=display):session.restore('token')
        display.apply.assert_not_called();self.assertFalse(self.file.exists())
    def test_prepare_persists_rollback_before_mutation(self):
        display=MagicMock();display.primary='DP-1';display.layout=[(0,0,1.,0,True,[('DP-1','old',{})])];display.mode.return_value='new'
        def verify(*args):self.assertEqual(json.loads(self.file.read_text())['previous'],'old')
        display.only.side_effect=verify
        with patch.object(session,'Display',return_value=display),patch.object(session,'invocation_id',return_value='a'),patch.dict(session.os.environ,SUNSHINE_CLIENT_WIDTH='1080',SUNSHINE_CLIENT_HEIGHT='1920'):
            session.prepare()
        display.only.assert_called_once()
    def test_active_lease_rejects_second_prepare(self):
        atomic_json(self.file,self.record())
        with patch.object(session,'invocation_id',return_value='a'):
            with self.assertRaises(RuntimeError):session.prepare()

    def test_prepared_lease_uses_monotonic_clock(self):
        record=self.record(started_monotonic=time.monotonic())
        record['started']-=3600
        self.assertTrue(session.lease_alive(record,'a'))
