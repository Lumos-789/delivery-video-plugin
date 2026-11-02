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


if __name__ == "__main__":
    unittest.main()
