import sys
import types
import unittest
import json
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dv_gate  # noqa: E402


class DetectParsingTests(unittest.TestCase):
    def test_blackdetect_line_without_space_after_colon_parses(self):
        log = ("[Parsed_blackdetect_0 @ 0x763d018c00] "
               "black_start:6 black_end:11.966667 black_duration:5.966667")
        self.assertEqual(
            dv_gate.parse_detects(log, "start"),
            [{"start": 6.0, "end": 11.966667}],
        )

    def test_silence_and_freeze_lines_with_space_parse(self):
        log = (
            "[Parsed_silencedetect_0 @ 0x7a41010c00] silence_start: 2.5\n"
            "[Parsed_silencedetect_0 @ 0x7a41010c00] silence_end: 5 | silence_duration: 2.5\n"
            "[Parsed_freezedetect_0 @ 0x7cc7018c00] lavfi.freezedetect.freeze_start: 6\n"
        )
        spans = dv_gate.parse_detects(log, "start")
        self.assertEqual(spans[0], {"start": 2.5, "end": 5.0})
        self.assertEqual(spans[1], {"start": 6.0})

    def test_trailing_start_without_end_is_kept(self):
        self.assertEqual(
            dv_gate.parse_detects("freeze_start: 4", "start"),
            [{"start": 4.0}],
        )


class QualityGateDetectTests(unittest.TestCase):
    """Gate level: ffmpeg-format detect logs drive B101/T301/T304."""

    DURATION = 12.0

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix="dv-gate-detect-")
        root = Path(self._tmp.name)
        self.video = root / "screen_demo.mp4"
        self.video.write_bytes(b"0" * 16)
        self.work = root / "gate"

    def tearDown(self):
        self._tmp.cleanup()

    def run_gate(self, detect_logs: dict[str, str], frame_rate: str = "30/1",
                exempt: list | None = None) -> dict:
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264",
                 "width": 1920, "height": 1080, "avg_frame_rate": frame_rate},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": str(self.DURATION), "size": "1500000"},
        }
        loudnorm = '[loudnorm @ 0x0] {\n "input_i" : "-14.0"\n}\n'

        def fake_run(args, **_kwargs):
            if args[0] == "ffprobe":
                return types.SimpleNamespace(
                    returncode=0, stdout=json.dumps(probe), stderr="")
            joined = " ".join(args)
            for token, log in detect_logs.items():
                if token in joined:
                    return types.SimpleNamespace(returncode=0, stdout="", stderr=log)
            if "loudnorm" in joined:
                return types.SimpleNamespace(returncode=0, stdout="", stderr=loudnorm)
            raise AssertionError(f"unexpected command: {args}")

        with mock.patch.object(dv_gate.subprocess, "run", side_effect=fake_run):
            return dv_gate.quality_gate(self.video, self.work, exempt)

    def test_black_without_space_after_colon_triggers_b101(self):
        report = self.run_gate({
            "blackdetect": ("[Parsed_blackdetect_0 @ 0x763d018c00] "
                            "black_start:6 black_end:11.966667 black_duration:5.966667"),
            "freezedetect": "",
            "silencedetect": "",
        })
        codes = [item["code"] for item in report["hard_failures"]]
        self.assertIn("B101", codes)
        self.assertEqual(report["checks"]["black_spans"], [{"start": 6.0, "end": 11.97}])
        self.assertEqual(report["status"], "fail")

    def test_freeze_to_eof_closes_at_total_duration(self):
        report = self.run_gate({
            "blackdetect": "",
            "freezedetect": ("[Parsed_freezedetect_0 @ 0x7cc7018c00] "
                             "lavfi.freezedetect.freeze_start: 6"),
            "silencedetect": "",
        })
        codes = [item["code"] for item in report["hard_failures"]]
        self.assertIn("T301", codes)
        self.assertIn("T304", codes)
        self.assertEqual(report["checks"]["freeze_spans"], [{"start": 6.0, "end": 12.0}])
        self.assertEqual(report["status"], "fail")

    def test_unparsable_frame_rate_fails_as_m102_not_traceback(self):
        report = self.run_gate({
            "blackdetect": "",
            "freezedetect": "",
            "silencedetect": "",
        }, frame_rate="0/0")
        codes = [item["code"] for item in report["hard_failures"]]
        self.assertIn("M102", codes)
        self.assertEqual(report["status"], "fail")


    def test_exempt_intervals_hide_freeze_and_silence_inside_them(self):
        logs = {
            "blackdetect": "",
            "freezedetect": "[Parsed_freezedetect_0 @ 0x7cc7018c00] "
                            "lavfi.freezedetect.freeze_start: 0.2\n"
                            "lavfi.freezedetect.freeze_end: 2.8\n",
            "silencedetect": "[Parsed_silencedetect_0 @ 0x7a41010c00] silence_start: 0.1\n"
                             "[Parsed_silencedetect_0 @ 0x7a41010c00] silence_end: 2.9\n",
        }
        card = [{"start": 0.0, "end": 3.0}]

        plain = self.run_gate(logs)
        exempt = self.run_gate(logs, exempt=card)

        self.assertIn("T301", [item["code"] for item in plain["hard_failures"]])
        self.assertEqual(exempt["status"], "pass")
        self.assertEqual(exempt["checks"]["freeze_spans"], [])
        self.assertEqual(exempt["checks"]["silence_spans"], [])
        self.assertEqual(exempt["exempt"]["seconds"], 3.0)

    def test_only_the_part_of_a_span_outside_the_card_counts(self):
        logs = {
            "blackdetect": "",
            "freezedetect": "[Parsed_freezedetect_0 @ 0x7cc7018c00] "
                            "lavfi.freezedetect.freeze_start: 2.0\n"
                            "lavfi.freezedetect.freeze_end: 4.0\n",
            "silencedetect": "",
        }
        report = self.run_gate(logs, exempt=[{"start": 0.0, "end": 2.5}])
        self.assertEqual(report["checks"]["freeze_spans"], [{"start": 2.5, "end": 4.0}])
        self.assertEqual(report["status"], "pass")

    def test_cards_may_not_cover_more_than_a_quarter_of_the_video(self):
        report = self.run_gate({"blackdetect": "", "freezedetect": "", "silencedetect": ""},
                               exempt=[{"start": 0.0, "end": 4.0}, {"start": 6.0, "end": 11.0}])
        self.assertIn("C301", [item["code"] for item in report["hard_failures"]])
        self.assertEqual(report["status"], "fail")


if __name__ == "__main__":
    unittest.main()
