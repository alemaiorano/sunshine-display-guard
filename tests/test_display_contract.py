"""Exercise the real Mutter apply boundary, including fixed-layout backends."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sunshine_session_display import Display


class DisplayApplyContractTests(unittest.TestCase):
    def apply(self, options):
        display = object.__new__(Display)
        display.serial = 7
        display.options = options
        display.modes = {'Virtual-1': [('hd', 1920, 1080, 60., 1., [1.], {})]}
        received = []

        def compositor(method, value):
            serial, apply_method, layout, properties = value.unpack()
            self.assertEqual((method, serial, apply_method), ('ApplyMonitorsConfig', 7, 1))
            if not options.get('supports-changing-layout-mode') and 'layout-mode' in properties:
                raise ValueError("Can't set layout mode")
            received.append((layout, properties))

        display.call = compositor
        display.only('Virtual-1', 'hd')
        return received[0]

    def test_fixed_layout_backend_omits_unsupported_property(self):
        for options in ({'layout-mode': 2},
                        {'layout-mode': 1, 'supports-changing-layout-mode': False}, {}):
            with self.subTest(options=options):
                layout, properties = self.apply(options)
                self.assertTrue(layout)
                self.assertNotIn('layout-mode', properties)

    def test_changeable_layout_backend_preserves_explicit_mode(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                _, properties = self.apply({'layout-mode': mode,
                                            'supports-changing-layout-mode': True})
                self.assertEqual(properties['layout-mode'], mode)
