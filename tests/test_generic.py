import contextlib
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import guard_config as config
import sunshine_session_display as session
import sunshine_observer as observer
import app_hooks
import generate_edid
from test_sunshine_regressions import Fixture


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'config.json'
    def load(self,value):
        self.path.write_text(json.dumps(value));return config.load(self.path)
    def test_defaults_do_not_choose_a_reserve_or_follow_primary(self):
        v=config.load(self.path);self.assertIsNone(v.reserve_connector);self.assertFalse(v.follow_primary)
    def test_missing_required_configuration_fails(self):
        with self.assertRaises(ValueError):config.load(self.path,True)
    def test_arbitrary_host_connector_and_system_scope(self):
        v=self.load(dict(reserve_connector='HDMI-A-7',sunshine_scope='system',moonlight_host='host.example'))
        self.assertEqual(v.unit_flags,[]);self.assertEqual(v.reserve_connector,'HDMI-A-7')
    def test_unknown_options_types_injection_and_invalid_ports_rejected(self):
        for value in [[],{'unknown':1},{'video_port':True},{'video_port':0},{'video_port':65536},{'sunshine_unit':'--help'},{'reserve_connector':'DP-1;touch /x'},{'moonlight_host':'--help'},{'moonlight_host':'host\nexample'},{'follow_primary':1},{'follow_primary':True},{'resolution_fps_limits':{'2560x1080':True}}]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.load(value)
    def test_large_json_rejected(self):
        self.path.write_bytes(b' '*65537)
        with self.assertRaises(ValueError):config.load(self.path)
    def test_json_recursion_has_clear_error(self):
        self.path.write_text('['*20000+'0'+']'*20000)
        with self.assertRaises(ValueError):config.load(self.path)


class JournalFailureTests(Fixture):
    def test_dead_journal_and_eof_do_not_end_healthy_video(self):
        r=self.record(started_monotonic=0.)
        session.atomic_json(self.lease,r)
        journal=MagicMock();journal.poll.return_value=0
        selector=MagicMock();selector.select.side_effect=[[(None,None)],[]]
        with patch.object(session.subprocess,'Popen',return_value=MagicMock(__enter__=MagicMock(return_value=journal))),patch.object(session.selectors,'DefaultSelector',return_value=MagicMock(__enter__=MagicMock(return_value=selector))),patch.object(session.os,'read',return_value=b''),patch.object(session,'stream_alive',side_effect=[True,True,False]),patch.object(session,'video_health',return_value=True),patch.object(session,'read_activity',return_value=None):
            session.watch_session(r)
        self.assertEqual(selector.select.call_count,2)
        selector.unregister.assert_called_once_with(journal.stdout)
        journal.terminate.assert_not_called()
    def test_oversized_lease_is_quarantined(self):
        self.lease.write_bytes(b' '*65537)
        self.assertIsNone(session.read_lease());self.assertFalse(self.lease.exists())
    def test_wrong_video_port_is_unavailable_not_false_session_end(self):
        with patch.object(observer,'read_snapshot',return_value={'video_port':49000}):
            self.assertIsNone(observer.video_health({'video_port':47998},100))
    def test_nonrunning_sunshine_is_rejected_before_lease_write(self):
        with patch.object(session,'invocation_id',return_value=''):
            with self.assertRaises(RuntimeError):session.prepare()
        self.assertFalse(self.lease.exists())


class AppHookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'apps.json'
        self.path.write_text(json.dumps({'apps':[{'name':'Existing','cmd':'preserve'}]}));self.path.chmod(0o600)
        for name,value in [('init_paths',lambda:None),('runtime_dir',lambda:self.root),('state_dir',lambda:self.root)]:
            p=patch.object(app_hooks,name,value);p.start();self.addCleanup(p.stop)
    def test_preview_never_touches_config(self):
        before=self.path.read_bytes();result=app_hooks.update(self.path,'New')
        self.assertFalse(result['writes_files']);self.assertEqual(self.path.read_bytes(),before)
    def test_apply_creates_separate_app_and_private_backup(self):
        before=self.path.read_bytes();result=app_hooks.update(self.path,'New',True)
        current=json.loads(self.path.read_text());self.assertEqual(current['apps'][0],{'name':'Existing','cmd':'preserve'})
        self.assertEqual(Path(result['backup']).read_bytes(),before)
        self.assertEqual(Path(result['backup']).stat().st_mode&0o777,0o600)
    def test_existing_app_never_overwritten(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):app_hooks.update(self.path,'Existing',True)
        self.assertEqual(self.path.read_bytes(),before)
    def test_symlink_is_rejected(self):
        link=self.root/'link.json';link.symlink_to(self.path)
        with self.assertRaises(ValueError):app_hooks.update(link,'New',True)


class EdidTests(unittest.TestCase):
    def test_modes_checksums_and_clock_ceiling(self):
        modes=[(1920,1080,60),(1080,1920,60),(1024,768,60),(2560,1080,50),(1080,2560,50)]
        data=generate_edid.generate(modes)
        self.assertEqual(len(data),(data[126]+1)*128)
        for offset in range(0,len(data),128):self.assertEqual(sum(data[offset:offset+128])%256,0)
        self.assertEqual(data[8:10],bytes.fromhex('6b56'))
    def test_unsafe_dimensions_and_pixel_clock_fail(self):
        for mode in [(5120,1440,60),(2560,1080,240),(1920,1080,0)]:
            with self.assertRaises(ValueError):generate_edid.generate([mode])

class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'credentials.json'
        self.path.write_text(json.dumps({'username':'fixture','password':'fixture'}));self.path.chmod(0o600)
    def test_private_valid_credentials_are_read_without_logging(self):
        self.assertEqual(config.read_credentials(self.path)['username'],'fixture')
    def test_world_readable_file_and_directory_are_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):config.read_credentials(self.path)
        with self.assertRaises(ValueError):config.read_credentials(self.path.parent)
    def test_invalid_fields_do_not_leak_values_into_error(self):
        self.path.write_text(json.dumps({'username':'fixture:marker','password':'private-test-marker'}))
        with self.assertRaises(ValueError) as error:config.read_credentials(self.path)
        self.assertNotIn('private-test-marker',str(error.exception))
    def test_oversized_file_is_rejected(self):
        self.path.write_bytes(b' '*16385)
        with self.assertRaises(ValueError):config.read_credentials(self.path)

class RefreshTests(Fixture):
    def test_session_refresh_is_not_silently_capped_to_sixty(self):
        d=self.display([(0,0,1.,0,True,[('DP-1','hd',{})])])
        with patch.object(d,'mode',wraps=d.mode) as choose,patch.dict(os.environ,SUNSHINE_CLIENT_WIDTH='1920',SUNSHINE_CLIENT_HEIGHT='1080',SUNSHINE_CLIENT_FPS='144'):
            session.prepare()
        self.assertEqual(choose.call_args.args[-1],144)

class DiagnosticTests(unittest.TestCase):
    def test_bad_sunshine_service_does_not_hide_available_graphical_session(self):
        import diagnose
        display=types.SimpleNamespace(modes={},layout=[])
        with patch.object(session,'Display',return_value=display),patch.object(session,'invocation_id',side_effect=subprocess.CalledProcessError(1,['fixture'])),patch.object(diagnose,'read_snapshot',return_value=None):
            result=diagnose.diagnose()
        self.assertTrue(result['checks']['graphical_session'])
        self.assertFalse(result['checks']['sunshine_running'])
        self.assertFalse(result['ready'])

class JournalScopeTests(unittest.TestCase):
    def test_user_and_system_journals_are_distinct_and_portable(self):
        self.assertEqual(config.journal_args('stream.service','user','fixture'),['--user-unit','stream.service','_SYSTEMD_INVOCATION_ID=fixture'])
        self.assertEqual(config.journal_args('stream.service','system','fixture'),['--unit','stream.service','_SYSTEMD_INVOCATION_ID=fixture'])
        self.assertFalse(any(x.startswith('--invocation') for x in config.journal_args('stream.service','user','fixture')))

class ExclusiveAppHookTests(unittest.TestCase):
    setUp=AppHookTests.setUp
    def test_exclusive_preview_is_explicit_and_does_not_write(self):
        before=self.path.read_bytes()
        result=app_hooks.update(self.path,'Remote',exclusive_reserve=True)
        self.assertTrue(result['app']['prep-cmd'][0]['do'].endswith(' prepare-remote'))
        self.assertFalse(result['writes_files']);self.assertEqual(before,self.path.read_bytes())
        self.assertTrue(app_hooks.application('Default')['prep-cmd'][0]['do'].endswith(' prepare'))

    def test_exclusive_apply_keeps_existing_apps_and_backup(self):
        before=self.path.read_bytes()
        result=app_hooks.update(self.path,'Remote',True,exclusive_reserve=True)
        data=json.loads(self.path.read_text())
        self.assertEqual(data['apps'][0],{'name':'Existing','cmd':'preserve'})
        self.assertTrue(data['apps'][1]['prep-cmd'][0]['do'].endswith(' prepare-remote'))
        self.assertEqual(Path(result['backup']).read_bytes(),before)
