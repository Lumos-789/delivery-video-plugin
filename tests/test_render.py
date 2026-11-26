import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import render  # noqa: E402


class SegmentFilterTests(unittest.TestCase):
    def test_missing_crop_is_full_frame(self):
        vf = render.segment_filter(None, "banded", 1.0, 5.0)
        self.assertNotIn("crop=", vf)
        self.assertIn("scale=1800:866", vf)

    def test_explicit_crop_comes_first(self):
        vf = render.segment_filter([10, 20, 300, 200], "banded", 1.0, 5.0)
        self.assertTrue(vf.startswith("crop=300:200:10:20,"))

    def test_fullbleed_fits_whole_canvas(self):
        vf = render.segment_filter(None, "fullbleed", 1.0, 5.0)
        self.assertNotIn("crop=", vf)
        self.assertIn("scale=1920:1080", vf)
        self.assertIn("pad=1920:1080:(ow-iw)/2:(oh-ih)/2", vf)


class NarrationFilterTests(unittest.TestCase):
    def test_narration_delay_is_derived_from_the_lead_constant(self):
        self.assertEqual(render.narration_filter(), "adelay=150:all=1,apad")
        with mock.patch.object(render, "LEAD", 0.3):
            self.assertEqual(render.narration_filter(), "adelay=300:all=1,apad")


if __name__ == "__main__":
    unittest.main()
