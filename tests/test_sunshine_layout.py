import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from sunshine_layout import normalize_layout, choose_mode
from test_desktop_policy import mode,row

class LayoutTests(unittest.TestCase):
    def setUp(self):self.modes={c:[mode()] for c in ['DP-1','DP-3','DP-4']}
    def test_duplicate_primary_repaired(self):
        result=normalize_layout([row('DP-3'),row('DP-4',True,1920)],self.modes)
        self.assertEqual(sum(r[4] for r in result),1)
    def test_no_primary_promoted(self):
        self.assertTrue(normalize_layout([row('DP-3',False)],self.modes)[0][4])
    def test_one_monitor_rebased(self):
        self.assertEqual(normalize_layout([row('DP-4',True,300,400)],self.modes)[0][:2],(0,0))
    def test_remove_virtual_primary(self):
        result=normalize_layout([row('DP-1'),row('DP-4',False,1920)],self.modes,exclude='DP-1')
        self.assertTrue(result[0][4]);self.assertEqual(result[0][:2],(0,0))
    def test_disconnect_primary(self):
        result=normalize_layout([row('DP-5'),row('DP-4',False,1920)],self.modes)
        self.assertTrue(result[0][4])
    def test_mirror_preserved(self):
        mirror=[(0,0,1.,0,True,[('DP-3','1080p',{}),('DP-4','1080p',{})])]
        self.assertEqual(normalize_layout(mirror,self.modes),mirror)
    def test_portrait_extension_preserved(self):
        layout=[row('DP-4'),row('DP-3',False,1920,0,1)]
        self.assertEqual(normalize_layout(layout,self.modes),layout)
    def test_stacked_preserved(self):
        layout=[row('DP-4'),row('DP-3',False,0,1080)]
        self.assertEqual(normalize_layout(layout,self.modes),layout)
    def test_gap_repacked(self):
        result=normalize_layout([row('DP-3'),row('DP-4',False,3000)],self.modes)
        self.assertEqual(result[1][0],1920)
    def test_overlap_repacked(self):
        result=normalize_layout([row('DP-3'),row('DP-4',False,100)],self.modes)
        self.assertEqual(result[1][0],1920)
    def test_negative_coordinates_normalized(self):
        result=normalize_layout([row('DP-3',True,-1920),row('DP-4',False,0)],self.modes)
        self.assertEqual(result[0][0],0);self.assertEqual(result[1][0],1920)
    def test_missing_mode_falls_back_to_preferred(self):
        self.modes['DP-4']=[mode('new',2560,1080)]
        self.assertEqual(normalize_layout([row('DP-4')],self.modes)[0][-1][0][1],'new')
    def test_scale_adjusted_to_available(self):
        self.modes['DP-4']=[mode(scale=(1.25,))]
        self.assertEqual(normalize_layout([row('DP-4')],self.modes)[0][2],1.25)
    def test_mirror_common_mode(self):
        self.modes['DP-3']=[mode('new',2560,1080),mode()]
        layout=[(0,0,1.,0,True,[('DP-3','new',{}),('DP-4','1080p',{})])]
        result=normalize_layout(layout,self.modes)
        self.assertEqual([m[1] for m in result[0][-1]],['1080p','1080p'])
    def test_impossible_mirror_rejected(self):
        self.modes['DP-3']=[mode('new',2560,1080)]
        with self.assertRaises(ValueError):normalize_layout([(0,0,1.,0,True,[('DP-3','new',{}),('DP-4','1080p',{})])],self.modes)
    def test_duplicate_connector_rejected(self):
        with self.assertRaises(ValueError):normalize_layout([row('DP-3'),row('DP-3')],self.modes)
    def test_bad_structure_rejected(self):
        with self.assertRaises((ValueError,TypeError)):normalize_layout([[]],self.modes)
    def test_bad_transform_rejected(self):
        with self.assertRaises(ValueError):normalize_layout([row(transform=8)],self.modes)
    def test_no_physical_returns_empty(self):
        self.assertEqual(normalize_layout([row('DP-1')],self.modes,exclude='DP-1'),[])
    def test_json_round_trip(self):
        layout=[row('DP-4'),row('DP-3',False,1920)]
        self.assertEqual(normalize_layout(json.loads(json.dumps(layout)),self.modes),layout)
    def test_exact_landscape(self):
        modes=[mode('phone',2340,1080),mode('wide',2560,1080)]
        self.assertEqual(choose_mode(modes,(2560,1080))[0],'wide')
    def test_exact_portrait(self):
        modes=[mode('phone',1080,2340),mode('vertical',1080,1920)]
        self.assertEqual(choose_mode(modes,(1080,1920))[0],'vertical')
    def test_aspect_before_pixel_area(self):
        modes=[mode('wide',2560,1080),mode('hd',1920,1080)]
        self.assertEqual(choose_mode(modes,(1280,720))[0],'hd')
    def test_invalid_size_rejected(self):
        with self.assertRaises(ValueError):choose_mode([mode()],(0,1080))

    def test_physical_layout_mode_does_not_divide_geometry_by_scale(self):
        layout=[(0,0,1.25,0,True,[('DP-3','1080p',{})]),
                (0,1080,1.25,0,False,[('DP-4','1080p',{})])]
        self.assertEqual(normalize_layout(layout,self.modes,layout_mode=2),layout)

    def test_physical_vrr_mode_is_preserved(self):
        self.modes['DP-3']=[mode(),mode('1080p+vrr')]
        layout=[(0,0,1.,0,True,[('DP-3','1080p+vrr',{})])]
        self.assertEqual(normalize_layout(layout,self.modes),layout)
    def test_mirror_keeps_selected_vrr_when_compatible(self):
        self.modes['DP-3']=[mode(),mode('1080p+vrr')]
        layout=[(0,0,1.,0,True,[('DP-3','1080p+vrr',{}),('DP-4','1080p',{})])]
        self.assertEqual(normalize_layout(layout,self.modes),layout)
