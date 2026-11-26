import shutil
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dv_core  # noqa: E402
import dv_tts  # noqa: E402
import fake_tts  # noqa: E402


def clock(text: str) -> list[str]:
    """Group a plain string as if every char took 200ms; returns the lines."""
    chars = [{"char": char, "start_ms": index * 200, "end_ms": index * 200 + 150}
             for index, char in enumerate(text)]
    return ["".join(char["char"] for char in line) for line in dv_tts.group_lines(chars)]


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

        chars = dv_tts.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)
        self.assertIn("，", [char["char"] for char in chars])
        self.assertEqual(chars[-1]["char"], "。")

    def test_a_word_boundary_missing_from_the_text_fails_loud(self):
        with self.assertRaisesRegex(dv_core.RenderError, "not present in narration"):
            dv_tts.align_clock("保存成功", [{"char": "提交", "start_ms": 0, "end_ms": 200}])

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

        self.assertEqual(clock(text), ["先保存任务。", "再刷新页面。", "检查结果。"])

    def test_grouping_breaks_long_lines_at_soft_punctuation_or_the_cap(self):
        text = "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十"
        lines = [len(line) for line in clock(text)]
        self.assertEqual(sum(lines), len(text))
        self.assertTrue(all(length <= 26 for length in lines), lines)

    def test_alignment_keeps_spaces_between_latin_words(self):
        text = "Open the page."
        words = [
            {"char": "Open", "start_ms": 0, "end_ms": 300},
            {"char": "the", "start_ms": 350, "end_ms": 500},
            {"char": "page", "start_ms": 550, "end_ms": 800},
        ]

        chars = dv_tts.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)

    def test_alignment_keeps_space_after_punctuation(self):
        text = "任务完成. Next step."
        words = [
            {"char": "任务", "start_ms": 0, "end_ms": 200},
            {"char": "完成", "start_ms": 200, "end_ms": 400},
            {"char": "Next", "start_ms": 500, "end_ms": 700},
            {"char": "step", "start_ms": 750, "end_ms": 900},
        ]

        chars = dv_tts.align_clock(text, words)

        self.assertEqual("".join(char["char"] for char in chars), text)


class CacheNamingTests(unittest.TestCase):
    BASE = [Path("build"), "s1", "打开页面", "zh-CN-YunxiNeural", "+5%"]

    def test_cache_files_are_keyed_by_text_voice_and_rate(self):
        reference = dv_tts.cache_files(*self.BASE)
        self.assertEqual(reference, dv_tts.cache_files(*self.BASE))
        for index in (2, 3, 4):
            changed = list(self.BASE)
            changed[index] = str(changed[index]) + "x"
            self.assertNotEqual(reference, dv_tts.cache_files(*changed), index)

    def test_cache_files_live_under_tts_and_start_with_the_segment_id(self):
        mp3, clock = dv_tts.cache_files(*self.BASE)
        self.assertEqual(mp3.parent, Path("build") / "tts")
        self.assertTrue(mp3.name.startswith("s1.") and mp3.name.endswith(".mp3"), mp3.name)
        self.assertTrue(clock.name.startswith("s1.") and clock.name.endswith(".json"), clock.name)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class SynthTests(unittest.TestCase):
    SEGMENT = {"id": "s1", "text": "打开页面点击保存"}
    VOICE, RATE = "zh-CN-YunxiNeural", "+5%"

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix="dv-tts-")
        self.build = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def synth(self, segment: dict):
        import asyncio
        return asyncio.run(dv_tts.synth(segment, self.VOICE, self.RATE, self.build))

    def cached(self, segment: dict) -> tuple[Path, Path]:
        return dv_tts.cache_files(self.build, segment["id"], segment["text"], self.VOICE, self.RATE)

    def test_a_cached_narration_is_reused_without_calling_the_service(self):
        calls = fake_tts.fake_edge_tts(self)
        first = self.synth(self.SEGMENT)
        second = self.synth(self.SEGMENT)

        self.assertEqual(len(calls), 1)
        self.assertEqual((first.mp3, first.seconds), (second.mp3, second.seconds))
        mp3, clock = self.cached(self.SEGMENT)
        self.assertTrue(mp3.is_file() and clock.is_file())
        self.assertEqual(first.mp3, mp3)
        self.assertEqual("".join(char["char"] for char in first.chars), self.SEGMENT["text"])
        self.assertAlmostEqual(first.seconds, 2.667, delta=0.04)

    def test_changed_narration_synthesizes_afresh_without_manual_deletion(self):
        calls = fake_tts.fake_edge_tts(self)
        self.synth(self.SEGMENT)
        edited = dict(self.SEGMENT, text="改成另一句旁白")

        result = self.synth(edited)

        self.assertEqual([call["text"] for call in calls], [self.SEGMENT["text"], edited["text"]])
        self.assertEqual(result.mp3, self.cached(edited)[0])
        self.assertEqual("".join(char["char"] for char in result.chars), edited["text"])
        self.assertTrue(self.cached(self.SEGMENT)[0].is_file())

    def test_service_errors_become_clean_failures_naming_the_segment(self):
        import edge_tts
        for error in (edge_tts.exceptions.NoAudioReceived("simulated: no audio"),
                      TimeoutError("simulated timeout")):
            with self.subTest(error=type(error).__name__):
                fake_tts.fake_edge_tts(self, error=error)
                with self.assertRaisesRegex(dv_core.RenderError,
                                            "synthesis failed for s1: " + type(error).__name__) as caught:
                    self.synth(self.SEGMENT)
                self.assertIn("rerun", str(caught.exception))
                self.assertFalse(self.cached(self.SEGMENT)[0].exists())

    def test_an_incomplete_cache_pair_is_re_synthesized(self):
        calls = fake_tts.fake_edge_tts(self)
        self.synth(self.SEGMENT)
        mp3, clock = self.cached(self.SEGMENT)
        clock.unlink()

        result = self.synth(self.SEGMENT)

        self.assertEqual(len(calls), 2)
        self.assertTrue(mp3.is_file() and clock.is_file())
        self.assertEqual("".join(char["char"] for char in result.chars), self.SEGMENT["text"])

    def test_nothing_is_left_behind_when_synthesis_fails(self):
        fake_tts.fake_edge_tts(self, error=TimeoutError("simulated timeout"))
        with self.assertRaises(dv_core.RenderError):
            self.synth(self.SEGMENT)
        self.assertEqual(list(self.build.iterdir()), [])

    def test_a_corrupt_clock_cache_fails_with_a_delete_hint(self):
        fake_tts.fake_edge_tts(self)
        self.synth(self.SEGMENT)
        mp3, clock = self.cached(self.SEGMENT)
        clock.write_text("{", encoding="utf-8")

        with self.assertRaisesRegex(dv_core.RenderError, "corrupt TTS clock.*delete"):
            self.synth(self.SEGMENT)


if __name__ == "__main__":
    unittest.main()
