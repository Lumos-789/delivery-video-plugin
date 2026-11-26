import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dv_episode  # noqa: E402


def errors_for(build: Path, episode: dict) -> list[str]:
    report = dv_episode.Validation()
    dv_episode.validate_episode(build, episode, report)
    return report.errors


class EvidenceBlockTests(unittest.TestCase):
    """The optional version-evidence block; segments here stop before any probing."""

    def errors(self, evidence: object) -> list[str]:
        return errors_for(Path("."), {"voice": "v", "segments": [{"id": "s1"}],
                                      "evidence": evidence})

    def test_scalars_and_lists_are_accepted(self):
        self.assertFalse(any("evidence must be" in error for error in
                             self.errors({"git_sha": "abc", "build": 12, "ratio": 0.5,
                                          "tickets": ["T-1", "T-2"]})))

    def test_nested_values_and_non_objects_are_rejected(self):
        self.assertTrue(any("evidence must be" in error for error in
                            self.errors({"meta": {"sha": "abc"}})))
        self.assertTrue(any("evidence must be" in error for error in self.errors(["abc"])))
        self.assertTrue(any("evidence must be" in error for error in self.errors({" ": "x"})))


class PolyphoneLintTests(unittest.TestCase):
    def warnings_for(self, text: str) -> list[str]:
        report = dv_episode.Validation()
        dv_episode.check_polyphones([text], report)
        return report.warnings

    def test_everyday_words_with_one_reading_stay_quiet(self):
        for text in [
            "保存成功，结果立即生效。", "系统提示数据已经更新。", "顶部弹出成功提示。",
            "字段还是空的，还能继续。", "现在都在线，一个都不选。", "页面重新加载，重点看名称。",
            "最长五分钟，超长消息会截断。", "这轮结果仍然对应场景。", "盯着页面，接着推进。",
            "人数和视频数都对得上。", "他在干什么，接着干。", "页面写得清清楚楚，我觉得没问题。",
            "差异和误差都在范围内。", "应该会响应。", "和联系信息对得上。", "屏幕刷新干净。",
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.warnings_for(text), [])

    def test_genuinely_ambiguous_uses_are_still_flagged(self):
        for text, char in [
            ("这一行还有字", "行"), ("取的行", "行"), ("字段很结实", "结"), ("系好安全带", "系"),
            ("通知被屏蔽", "屏"), ("归还书本", "还"), ("首都是北京", "都"), ("数不清", "数"),
            ("他着急了", "着"), ("着手准备", "着"), ("还是差得远", "差"), ("这得看情况", "得"),
            ("这事不相干", "干"),
        ]:
            with self.subTest(text=text):
                warnings = self.warnings_for(text)
                self.assertEqual(len(warnings), 1, warnings)
                self.assertIn(f"polyphone '{char}'", warnings[0])

    def test_each_real_hit_carries_the_reading_hint_and_context(self):
        warning = self.warnings_for("这一行还有字")[0]
        self.assertIn("háng", warning)
        self.assertIn("…这一行还有字…", warning)

    def test_a_safe_word_wins_over_a_watched_pattern_inside_it(self):
        self.assertEqual(self.warnings_for("值得等一等，对得上"), [])


class NarrationLengthTests(unittest.TestCase):
    def warnings_for(self, text: str) -> list[str]:
        report = dv_episode.Validation()
        dv_episode.check_length([text], report)
        return report.warnings

    def test_a_long_single_thought_is_flagged(self):
        warnings = self.warnings_for("顺" * 51)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("narration 1: long", warnings[0])
        self.assertIn("51", warnings[0])

    def test_normal_chinese_and_english_lines_stay_quiet(self):
        self.assertEqual(self.warnings_for("顺" * 50), [])
        self.assertEqual(self.warnings_for("Open the page and click save, "
                                           "then the list shows the new owner."), [])

    def test_latin_text_is_weighed_by_speaking_time(self):
        self.assertEqual(len(self.warnings_for("a" * 300)), 1)


class TopLevelRuleTests(unittest.TestCase):
    def test_the_default_layout_is_fullbleed(self):
        report = dv_episode.Validation()
        dv_episode.validate_episode(Path("."), {"voice": "v", "segments": []}, report)
        self.assertEqual(report.layout, "fullbleed")
        report = dv_episode.Validation()
        dv_episode.validate_episode(Path("."), {"voice": "v", "layout": "banded", "segments": []},
                                    report)
        self.assertEqual(report.layout, "banded")

    def test_rate_and_layout_are_checked_before_segments(self):
        errors = errors_for(Path("."), {"voice": "v", "rate": "fast", "layout": "wide",
                                        "segments": []})
        self.assertIn("rate must look like +5% or -10%, got 'fast'", errors)
        self.assertIn("layout must be one of ['banded', 'fullbleed'], got 'wide'", errors)
        self.assertIn("segments must be a non-empty array", errors)

    def test_segment_ids_must_be_safe_file_stems(self):
        errors = errors_for(Path("."), {"voice": "v", "segments": [{"id": "a/b"},
                                                                   {"id": "it's"},
                                                                   {"id": "ok-1"},
                                                                   {"id": "ok-1"}]})
        self.assertEqual(sum("id must be ASCII" in error for error in errors), 2)
        self.assertEqual(sum("duplicate id" in error for error in errors), 1)


if __name__ == "__main__":
    unittest.main()
