"""Startup races must not lose a capture restart or retry indefinitely."""
from dataclasses import replace
import http.client
import importlib.util
import io
from pathlib import Path
import types
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import unittest
from unittest.mock import MagicMock, patch
import urllib.error


SPEC = importlib.util.spec_from_file_location(
    'display_awake', Path(__file__).resolve().parents[1] / 'scripts/keep-display-awake.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(HELPER,'RESTART_STATE',Path(self.temp.name)/'restart.json');p.start();self.addCleanup(p.stop)
        for name,value in [('lease_lock',MagicMock()),('read_lease',MagicMock(return_value=None)),('read_snapshot',MagicMock(return_value=None))]:
            p=patch.object(HELPER,name,value);p.start();self.addCleanup(p.stop)
        self.glib = MagicMock()
        self.glib.timeout_add_seconds.return_value = 42
        for name, value in [('GLib', self.glib), ('restart_source', None)]:
            p = patch.object(HELPER, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        self.credential_path=Path(self.temp.name)/'credentials.json'
        self.credential_path.write_text('{"username":"fixture","password":"fixture"}')
        self.credential_path.chmod(0o600)
        p=patch.object(HELPER,'SETTINGS',replace(HELPER.SETTINGS,follow_primary=True,restart_credentials=str(self.credential_path)))
        p.start();self.addCleanup(p.stop)
        p = patch.object(HELPER.urllib.request, 'urlopen')
        self.urlopen = p.start()
        self.addCleanup(p.stop)
        self.output = io.StringIO()
        p = patch('sys.stdout', self.output)
        p.start()
        self.addCleanup(p.stop)

    def test_api_not_ready_then_success(self):
        self.urlopen.side_effect = [urllib.error.URLError('refused'), MagicMock()]
        self.assertFalse(HELPER.restart_sunshine())
        self.glib.timeout_add_seconds.assert_called_once_with(5, HELPER.restart_sunshine, 1)
        self.assertEqual(HELPER.restart_source, 42)
        self.assertFalse(HELPER.restart_sunshine(1))
        self.assertIsNone(HELPER.restart_source)
        self.assertEqual(self.urlopen.call_count, 2)
        self.assertNotIn('fixture', self.output.getvalue())

    def test_failure_stops_after_four_attempts(self):
        self.urlopen.side_effect = TimeoutError()
        for attempt in range(4):
            self.assertFalse(HELPER.restart_sunshine(attempt))
        self.assertEqual(self.urlopen.call_count, 4)
        self.assertEqual(self.glib.timeout_add_seconds.call_count, 3)
        self.assertIsNone(HELPER.restart_source)
        self.assertIn('retries exhausted', self.output.getvalue())

    def test_http_auth_failure_does_not_retry(self):
        self.urlopen.side_effect = urllib.error.HTTPError('https://localhost', 401, '', {}, None)
        HELPER.restart_sunshine()
        self.glib.timeout_add_seconds.assert_not_called()
        self.assertIn('HTTP 401', self.output.getvalue())

    def test_http_server_failure_retries(self):
        self.urlopen.side_effect = urllib.error.HTTPError('https://localhost', 503, '', {}, None)
        HELPER.restart_sunshine()
        self.glib.timeout_add_seconds.assert_called_once()

    def test_restart_disconnect_counts_as_accepted(self):
        self.urlopen.side_effect = http.client.RemoteDisconnected()
        HELPER.restart_sunshine()
        self.glib.timeout_add_seconds.assert_not_called()

    def test_bad_credentials_file_does_not_retry_or_crash(self):
        self.credential_path.write_text('{}')
        HELPER.restart_sunshine()
        self.urlopen.assert_not_called()
        self.glib.timeout_add_seconds.assert_not_called()

    def test_new_selection_cancels_old_retry(self):
        HELPER.restart_source = 42
        HELPER.request_restart()
        self.glib.source_remove.assert_called_once_with(42)
        self.urlopen.assert_called_once()
        self.assertIsNone(HELPER.restart_source)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(HELPER,'RESTART_STATE',Path(self.temp.name)/'restart.json');p.start();self.addCleanup(p.stop)
        self.path = MagicMock()
        self.path.return_value.glob.return_value = ['connected']
        self.config = self.path.return_value.expanduser.return_value
        self.config.read_text.return_value = 'output_name = DP-4\nother = preserved\n'
        self.dbus = MagicMock()
        self.dbus.DBusException = RuntimeError
        self.dbus.Interface.return_value.GetCurrentState.return_value = [None, None, [
            [None, None, None, None, True, [['DP-4']]]]]
        self.restart = MagicMock()
        self.glib = MagicMock()
        for name, value in [('Path', self.path), ('dbus', self.dbus),
                            ('bus', MagicMock()), ('GLib', self.glib),
                            ('request_restart', self.restart), ('restart_pending', False),
                            ('SETTINGS',replace(HELPER.SETTINGS,follow_primary=True,restart_credentials='fixture')),
                            ('lease_lock', MagicMock()), ('read_lease', MagicMock(return_value=None)),
                            ('read_snapshot', MagicMock(return_value=None)),
                            ('sync_source', None), ('sync_force', False)]:
            p = patch.object(HELPER, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)
        p = patch('sys.stdout', io.StringIO())
        p.start()
        self.addCleanup(p.stop)

    def test_same_connector_is_idle_unless_forced(self):
        HELPER.sync_primary()
        self.restart.assert_not_called()
        HELPER.sync_primary(True)
        self.restart.assert_called_once()
        self.config.with_name.assert_not_called()

    def test_same_connector_retries_unconfirmed_restart_after_backoff(self):
        HELPER.restart_pending = True
        with patch.object(HELPER, 'restart_after', 0), patch.object(HELPER, 'restart_source', None):
            HELPER.sync_primary()
        self.restart.assert_called_once()

    def test_same_connector_waits_for_restart_backoff(self):
        HELPER.restart_pending = True
        with patch.object(HELPER, 'restart_after', float('inf')):
            HELPER.sync_primary()
        self.restart.assert_not_called()

    def test_changed_connector_preserves_other_settings_and_permissions(self):
        self.config.read_text.return_value = 'output_name = DP-3\nother = preserved\n'
        self.config.stat.return_value = types.SimpleNamespace(st_mode=0o100600)
        with patch.object(HELPER.os, 'replace') as replace:
            HELPER.sync_primary()
        temporary = self.config.with_name.return_value
        temporary.write_text.assert_called_once_with('other = preserved\noutput_name = DP-4\n')
        temporary.chmod.assert_called_once_with(0o600)
        self.assertEqual(replace.call_args_list[-1].args,(temporary,self.config))
        self.restart.assert_called_once()

    def test_compositor_event_forces_probe(self):
        HELPER.owner_changed(HELPER.NAME, '', ':1.2')
        self.assertEqual(self.glib.timeout_add.call_args_list[-1].args,
                         (3500, HELPER.sync_primary, True))

    def test_no_monitor_does_not_restart(self):
        self.dbus.Interface.return_value.GetCurrentState.return_value = [None, None, []]
        HELPER.sync_primary(True)
        self.restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
