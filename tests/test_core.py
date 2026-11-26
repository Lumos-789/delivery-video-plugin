import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dv_core  # noqa: E402


class ToolTests(unittest.TestCase):
    def test_missing_ffmpeg_tools_fail_with_an_actionable_message(self):
        with mock.patch.object(dv_core.shutil, "which", return_value=None):
            with self.assertRaisesRegex(dv_core.RenderError, "ffmpeg.*ffprobe"):
                dv_core.check_tools()

    def test_missing_cjk_font_fails_before_rendering(self):
        with mock.patch.object(dv_core, "FONT_CANDIDATES", []):
            with self.assertRaisesRegex(dv_core.RenderError, "CJK font"):
                dv_core.font_path()

    def test_font_face_is_simplified_chinese(self):
        family, style = dv_core.find_font(48).getname()
        self.assertFalse(family.endswith((" TC", " HK", " JP", " KR", " MO")), (family, style))
        if Path(dv_core.font_path()).name == "PingFang.ttc":
            self.assertEqual((family, style), ("PingFang SC", "Medium"))

    def test_pick_face_prefers_the_simplified_family_and_medium_weight(self):
        faces = [(0, "PingFang HK", "Regular"), (1, "PingFang HK", "Medium"),
                 (2, "PingFang SC", "Regular"), (3, "PingFang SC", "Medium")]
        self.assertEqual(dv_core.pick_face(faces), 3)
        self.assertEqual(dv_core.pick_face([(0, "Noto Sans CJK JP", "Regular"),
                                            (2, "Noto Sans CJK SC", "Regular")]), 2)
        self.assertEqual(dv_core.pick_face([(0, "Hiragino Sans GB", "W3")]), 0)
        self.assertEqual(dv_core.pick_face([]), 0)


class CropRuleTests(unittest.TestCase):
    def test_crop_inside_the_source_is_accepted(self):
        self.assertIsNone(dv_core.crop_error("s1", [10, 20, 300, 200], 1920, 1080))

    def test_crop_shape_and_booleans_are_rejected(self):
        self.assertIn("crop must be", dv_core.crop_error("s1", [1, 2, 3], 1920, 1080))
        self.assertIn("crop must be", dv_core.crop_error("s1", [1, 2, True, 4], 1920, 1080))

    def test_crop_origin_and_bounds_are_rejected(self):
        self.assertIn("negative origin", dv_core.crop_error("s1", [-1, 0, 10, 10], 1920, 1080))
        self.assertIn("non-positive size", dv_core.crop_error("s1", [0, 0, 0, 10], 1920, 1080))
        self.assertIsNone(dv_core.crop_error("s1", [1900, 0, 20, 1080], 1920, 1080))
        self.assertIn("exceeds source", dv_core.crop_error("s1", [1901, 0, 20, 10], 1920, 1080))


class FeedbackRuleTests(unittest.TestCase):
    def test_delivery_episode_keeps_the_existing_contract(self):
        self.assertEqual(dv_core.feedback_errors({"segments": []}, []), [])
        self.assertEqual(
            dv_core.feedback_errors({"intent": "delivery", "segments": []}, []), []
        )

    def test_feedback_requires_issue_fields_and_an_actual_segment(self):
        errors = dv_core.feedback_errors(
            {"intent": "feedback", "issue": {"title": "Save keeps old total"}},
            [{"id": "01-repro", "phase": "repro"}],
        )
        self.assertTrue(any("issue.severity" in error for error in errors))
        self.assertTrue(any("issue.expected" in error for error in errors))
        self.assertTrue(any("issue.actual" in error for error in errors))
        self.assertTrue(any("phase 'actual'" in error for error in errors))

    def test_feedback_rejects_unknown_severity_and_phase(self):
        errors = dv_core.feedback_errors(
            {
                "intent": "feedback",
                "issue": {
                    "title": "Save keeps old total",
                    "severity": "urgent",
                    "expected": "The new total appears",
                    "actual": "The old total remains",
                },
            },
            [{"id": "01-actual", "phase": "symptom"}],
        )
        self.assertTrue(any("issue.severity" in error for error in errors))
        self.assertTrue(any("01-actual: phase" in error for error in errors))
        self.assertTrue(any("phase 'actual'" in error for error in errors))

    def test_feedback_accepts_a_complete_issue(self):
        errors = dv_core.feedback_errors(
            {
                "intent": "feedback",
                "issue": {
                    "title": "Save keeps old total",
                    "severity": "major",
                    "expected": "The new total appears",
                    "actual": "The old total remains",
                    "repro": ["Open the order", "Change the amount", "Save"],
                },
            },
            [
                {"id": "01-repro", "phase": "repro"},
                {"id": "02-actual", "phase": "actual"},
            ],
        )
        self.assertEqual(errors, [])

    def test_delivery_episode_rejects_phases(self):
        errors = dv_core.feedback_errors(
            {"segments": []}, [{"id": "01-entry", "phase": "repro"}]
        )
        self.assertTrue(any("phase is only valid" in error for error in errors))


class ContentHashTests(unittest.TestCase):
    def test_content_hash_is_formatting_independent(self):
        a = {"kind": "feedback", "issue": {"title": "x", "actual": "y"}}
        b = {"issue": {"actual": "y", "title": "x"}, "kind": "feedback"}
        self.assertEqual(dv_core.content_sha256(a), dv_core.content_sha256(b))
        self.assertNotEqual(
            dv_core.content_sha256(a),
            dv_core.content_sha256({"kind": "feedback", "issue": {"title": "x", "actual": "z"}}),
        )


if __name__ == "__main__":
    unittest.main()
