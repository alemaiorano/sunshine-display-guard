from dataclasses import replace
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('client',ROOT/'scripts/moonlight-client.py')
client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)


def monitor(connector,width,height):
    spec=(connector,'brand','model','serial')
    return (spec,[('id',width,height,60.,1.,[1.],{'is-current':True})],{'display-name':connector})

class ClientTests(unittest.TestCase):
    def test_virtual_alias_does_not_rename_physical_dell(self):
        for vendor, model in [('ZZV', 'Virtual')]:
            self.assertEqual(client.monitor_name(('DP-1', vendor, model, '0'), {}), 'Virtual monitor')
        self.assertEqual(client.monitor_name(('DP-3', 'DEL', 'U2720Q', '1'),
                                            {'display-name': 'Dell 27'}), 'Dell 27')

    def test_status_distinguishes_connected_inactive_and_unknown_panel_power(self):
        state=self.state()
        state[1].append(monitor('DP-1',1920,1080))
        with patch.object(client.Path, 'glob', return_value=[]):
            status=client.monitor_status(state)
        self.assertEqual([s['active'] for s in status], [True, True, False])
        self.assertTrue(all(s['connected'] and s['panel_power']=='unknown' for s in status))

    def state(self):
        a=monitor('DP-3',1920,1080);b=monitor('DP-4',2560,1080)
        return (1,[a,b],[(2560,0,1.,1,True,[a[0]],{}),(0,350,1.,0,False,[b[0]],{})],{})
    def test_horizontal_and_vertical_targets(self):
        targets=client.targets(self.state())
        self.assertEqual([(s['width'],s['height']) for s in targets],[(1080,1920),(2560,1080)])
    def test_select_nonprimary_horizontal(self):
        screen=client.choose_target(client.targets(self.state()),'DP-4')
        self.assertEqual((screen['width'],screen['height']),(2560,1080))
        self.assertIn('+20+390',client.window_geometry(screen))
    def test_select_portrait_geometry(self):
        screen=client.choose_target(client.targets(self.state()),'DP-3')
        self.assertIn('+2580+40',client.window_geometry(screen))
    def test_single_screen_has_no_dialog(self):
        with patch.object(client.subprocess,'run') as run:
            client.choose_target(client.targets(self.state())[:1]);run.assert_not_called()
    def test_mirror_is_single_target(self):
        s=self.state();logical=[(0,0,1.,0,True,[s[1][0][0],s[1][1][0]],{})]
        result=client.targets((s[0],s[1],logical,s[3]));self.assertEqual(len(result),1)
        self.assertEqual(result[0]['connectors'],['DP-3','DP-4'])
        self.assertEqual(client.choose_target(result,'DP-4'),result[0])
    def test_cancel_never_launches(self):
        with patch.object(client.subprocess,'run',return_value=MagicMock(returncode=1)):
            with self.assertRaises(SystemExit):client.choose_target(client.targets(self.state()))
    def test_disconnected_target_rejected(self):
        with self.assertRaises(StopIteration):client.choose_target(client.targets(self.state()),'DP-5')
    def test_scaled_geometry_fits_monitor(self):
        screen=client.targets(self.state())[0];screen['scale']=2.
        self.assertTrue(client.window_geometry(screen).startswith('500x600'))

    def test_ultrawide_limits_fps_to_source_refresh(self):
        with patch.object(client,'SETTINGS',replace(client.SETTINGS,resolution_fps_limits={'2560x1080':50})):
            self.assertEqual(client.client_fps(2560,1080,60),50)
    def test_fps_keeps_lower_user_preference(self):
        self.assertEqual(client.client_fps(2560,1080,30),30)
    def test_portrait_full_hd_keeps_sixty(self):
        self.assertEqual(client.client_fps(1080,1920,60),60)
