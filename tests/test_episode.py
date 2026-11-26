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


class CardRuleTests(unittest.TestCase):
    def errors(self, **card) -> list[str]:
        return errors_for(Path("."), {"voice": "v", "segments": [dict(card, id="c1", kind="card")]})

    def test_a_silent_card_needs_only_a_title(self):
        self.assertEqual(self.errors(title="两个用例全部通过"), [])
        self.assertEqual(self.errors(title="开场", duration=1, case="F-01"), [])

    def test_a_narrated_card_follows_its_narration(self):
        self.assertEqual(self.errors(title="订单名单 2.0", text="这次交付覆盖两个用例。"), [])
        self.assertIn("duration applies to silent cards",
                      self.errors(title="x", text="旁白。", duration=2)[0])

    def test_a_card_without_title_or_narration_is_rejected(self):
        self.assertEqual(self.errors(), ["c1: card needs a title or narration"])

    def test_a_silent_card_duration_stays_in_range(self):
        self.assertEqual(self.errors(title="x", duration=0.5),
                         ["c1: card duration must be a number within 1..8s"])
        self.assertEqual(self.errors(title="x", duration=9),
                         ["c1: card duration must be a number within 1..8s"])

    def test_a_card_cannot_carry_footage(self):
        errors = self.errors(title="x", shot="take.mp4", start=0, end=2, source="window")
        self.assertEqual(sorted(errors), sorted([
            "c1: a card has no footage; drop 'shot'",
            "c1: a card has no footage; drop 'source'",
            "c1: a card has no footage; drop 'start'",
            "c1: a card has no footage; drop 'end'",
        ]))

    def test_a_card_title_must_fit_the_frame(self):
        self.assertIn("card title is too long", self.errors(title="标" * 41)[0])
        self.assertIn("card title must be a single non-empty line",
                      self.errors(title="第一行\n第二行")[0])


class TakePlacementTests(unittest.TestCase):
    def errors(self, shot: str) -> list[str]:
        return errors_for(Path("."), {"voice": "v", "segments": [
            {"id": "s1", "label": "l", "text": "旁白", "shot": shot, "start": 0, "end": 1}]})

    def test_a_take_may_not_sit_where_the_renderer_writes(self):
        for shot in ("screen_demo.mp4", "screen_demo.rendering.mp4", "tts/x.mp4",
                     "review/x.mp4", "clips/x.mp4", "quality_gate/x.mp4"):
            with self.subTest(shot=shot):
                self.assertTrue(any("is a file the renderer writes" in error
                                    for error in self.errors(shot)))

    def test_ordinary_take_paths_are_not_mistaken_for_renderer_outputs(self):
        self.assertFalse(any("renderer writes" in error for error in self.errors("takes/reviewed.mp4")))

    def test_ids_and_rates_reject_a_trailing_newline(self):
        errors = errors_for(Path("."), {"voice": "v", "segments": [{"id": "ok\n"}]})
        self.assertTrue(any("id must be ASCII" in error for error in errors), errors)
        errors = errors_for(Path("."), {"voice": "v", "rate": "+5%\n", "segments": []})
        self.assertTrue(any("rate must look like" in error for error in errors), errors)


class FieldTypeTests(unittest.TestCase):
    def errors(self, segment: dict, **episode) -> list[str]:
        return errors_for(Path("."), dict(episode, voice="v", segments=[segment]))

    def test_case_must_be_a_non_empty_string(self):
        for value in (123, ["F-01"], ""):
            with self.subTest(case=value):
                errors = self.errors({"id": "s1", "label": "l", "text": "旁白", "shot": "t.mp4",
                                      "start": 0, "end": 1, "case": value})
                self.assertTrue(any("case must be" in error for error in errors), errors)
        self.assertFalse(any("case must be" in error for error in
                             self.errors({"id": "s1", "case": "F-01"})))

    def test_a_card_label_must_be_a_string_when_present(self):
        for value in (5, ["x"], ""):
            with self.subTest(label=value):
                errors = self.errors({"id": "c1", "kind": "card", "title": "标题", "label": value})
                self.assertTrue(any("label must be" in error for error in errors), errors)

    def test_source_rejects_non_strings_without_crashing(self):
        for value in ([], {}, 5, True):
            with self.subTest(source=value):
                errors = self.errors({"id": "s1", "label": "l", "text": "旁白", "shot": "t.mp4",
                                      "start": 0, "end": 1, "source": value})
                self.assertTrue(any("source must be" in error for error in errors), errors)

    def test_phase_and_intent_reject_non_strings_without_crashing(self):
        issue = {"title": "t", "severity": "major", "expected": "e", "actual": "a"}
        errors = self.errors({"id": "a1", "phase": [], "text": "旁白"}, intent="feedback",
                             issue=issue)
        self.assertTrue(any("phase must be" in error for error in errors), errors)
        errors = errors_for(Path("."), {"voice": "v", "intent": [], "segments": [{"id": "a1"}]})
        self.assertTrue(any("intent must be" in error for error in errors), errors)
if __name__ == "__main__":
    unittest.main()
