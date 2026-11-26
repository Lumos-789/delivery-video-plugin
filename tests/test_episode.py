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


class TopLevelRuleTests(unittest.TestCase):
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
