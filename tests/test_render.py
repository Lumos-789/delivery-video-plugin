import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "delivery_video_render",
    ROOT / "skills" / "delivery-video" / "scripts" / "render.py",
)
render = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(render)


class ClockTests(unittest.TestCase):
    def test_alignment_preserves_chinese_punctuation(self):
        text = "改为高优先级，点击保存成功。"
        words = [
            {"char": "改为", "start_ms": 100, "end_ms": 300},
            {"char": "高", "start_ms": 320, "end_ms": 400},
            {"char": "优先级", "start_ms": 400, "end_ms": 700},
            {"char": "点击", "start_ms": 800, "end_ms": 1000},
            {"char": "保存", "start_ms": 1010, "end_ms": 1200},
            {"char": "成功", "start_ms": 1210, "end_ms": 1400},
        ]

        chars = render.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)
        self.assertIn("，", [char["char"] for char in chars])
        self.assertEqual(chars[-1]["char"], "。")

    def test_grouping_breaks_after_sentence_end(self):
        text = "先保存任务。再刷新页面。检查结果。"
        words = [
            {"char": "先保存", "start_ms": 0, "end_ms": 200},
            {"char": "任务", "start_ms": 200, "end_ms": 400},
            {"char": "再刷新", "start_ms": 500, "end_ms": 700},
            {"char": "页面", "start_ms": 700, "end_ms": 900},
            {"char": "检查", "start_ms": 1000, "end_ms": 1200},
            {"char": "结果", "start_ms": 1200, "end_ms": 1400},
        ]

        chars = render.align_clock(text, words)
        lines = ["".join(char["char"] for char in line) for line in render.group_lines(chars)]

        self.assertEqual(lines, ["先保存任务。", "再刷新页面。", "检查结果。"])

    def test_alignment_keeps_spaces_between_latin_words(self):
        text = "Open the page."
        words = [
            {"char": "Open", "start_ms": 0, "end_ms": 300},
            {"char": "the", "start_ms": 350, "end_ms": 500},
            {"char": "page", "start_ms": 550, "end_ms": 800},
        ]

        chars = render.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)

    def test_alignment_keeps_space_after_punctuation(self):
        text = "任务完成. Next step."
        words = [
            {"char": "任务", "start_ms": 0, "end_ms": 200},
            {"char": "完成", "start_ms": 200, "end_ms": 400},
            {"char": "Next", "start_ms": 500, "end_ms": 700},
            {"char": "step", "start_ms": 750, "end_ms": 900},
        ]

        chars = render.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)

    def test_missing_ffmpeg_tools_fail_with_an_actionable_message(self):
        with mock.patch.object(render.shutil, "which", return_value=None):
            with self.assertRaisesRegex(render.RenderError, "ffmpeg.*ffprobe"):
                render.check_tools()

    def test_missing_cjk_font_fails_before_rendering(self):
        with mock.patch.object(render, "FONT_CANDIDATES", []):
            with self.assertRaisesRegex(render.RenderError, "CJK font"):
                render.font_path()


class FeedbackTests(unittest.TestCase):
    def test_delivery_episode_keeps_the_existing_contract(self):
        self.assertEqual(render.feedback_errors({"segments": []}, []), [])
        self.assertEqual(
            render.feedback_errors({"intent": "delivery", "segments": []}, []), []
        )

    def test_feedback_requires_issue_fields_and_an_actual_segment(self):
        errors = render.feedback_errors(
            {"intent": "feedback", "issue": {"title": "Save keeps old total"}},
            [{"id": "01-repro", "phase": "repro"}],
        )
        self.assertTrue(any("issue.severity" in error for error in errors))
        self.assertTrue(any("issue.expected" in error for error in errors))
        self.assertTrue(any("issue.actual" in error for error in errors))
        self.assertTrue(any("phase 'actual'" in error for error in errors))

    def test_feedback_rejects_unknown_severity_and_phase(self):
        errors = render.feedback_errors(
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
        errors = render.feedback_errors(
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
        errors = render.feedback_errors(
            {"segments": []}, [{"id": "01-entry", "phase": "repro"}]
        )
        self.assertTrue(any("phase is only valid" in error for error in errors))

    def test_feedback_markdown_carries_the_issue_and_timeline(self):
        issue = {
            "id": "BUG-1",
            "title": "Save keeps old total",
            "severity": "major",
            "environment": "staging",
            "expected": "The new total appears",
            "actual": "The old total remains",
            "repro": ["Open the order", "Change the amount", "Save"],
        }
        segments = [
            {"id": "01-repro", "phase": "repro"},
            {"id": "02-actual", "phase": "actual"},
        ]
        timeline = [
            {"id": "01-repro", "start": 0.0, "end": 7.3,
             "source": "take-01.mp4", "source_start": 0.5, "source_end": 11.0},
            {"id": "02-actual", "start": 7.3, "end": 12.5,
             "source": "take-02.mp4", "source_start": 0.5, "source_end": 9.0},
        ]
        report = {
            "duration_s": 12.5,
            "video_sha256": "abc123",
            "status": "pass",
            "profile": "delivery-v1",
            "score": {"total": 100},
        }

        markdown = render.feedback_markdown(issue, segments, timeline, report)

        self.assertIn("# BUG-1 Save keeps old total", markdown)
        self.assertIn("- Severity: `major` (P2 MAJOR)", markdown)
        self.assertIn("1. Open the order", markdown)
        self.assertIn("3. Save", markdown)
        self.assertIn("| REPRO | 00:00.000-00:07.300 | `take-01.mp4` | 0.50-11.00s |", markdown)
        self.assertIn("SHA256 `abc123`", markdown)
        self.assertIn("Draft generated by render.py", markdown)

    def test_feedback_content_hash_is_formatting_independent(self):
        a = {"kind": "feedback", "issue": {"title": "x", "actual": "y"}}
        b = {"issue": {"actual": "y", "title": "x"}, "kind": "feedback"}
        self.assertEqual(
            render.feedback_content_sha256(a),
            render.feedback_content_sha256(b),
        )
        self.assertNotEqual(
            render.feedback_content_sha256(a),
            render.feedback_content_sha256(
                {"kind": "feedback", "issue": {"title": "x", "actual": "z"}}
            ),
        )


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


if __name__ == "__main__":
    unittest.main()
