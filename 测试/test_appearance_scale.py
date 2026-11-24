"""Readable values must preserve low legacy radii and unrestricted inputs."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scimol_c4d.appearance_scale import to_physical, to_display


class AppearanceScaleTests(unittest.TestCase):
    def test_endpoints_and_default_thickness(self):
        for key, low, high, a, b in (("atom_radius",1,5,.3,1),
                                     ("bond_radius",1,5,.05,.18),
                                     ("bond_spacing",1,5,.1,.4)):
            self.assertAlmostEqual(to_physical(key, low), a)
            self.assertAlmostEqual(to_physical(key, high), b)
        self.assertAlmostEqual(to_display("bond_radius",.08),2)
        self.assertAlmostEqual(to_display("bond_spacing",.18),2)

    def test_legacy_small_values_and_out_of_range_values_round_trip(self):
        for key in ("atom_radius", "bond_radius", "bond_spacing"):
            for value in (.005,.05,.3,1,3):
                with self.subTest(key=key,value=value):
                    display=to_display(key,value)
                    self.assertGreater(display,0)
                    self.assertAlmostEqual(to_physical(key,display),value)
