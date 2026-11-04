import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "delivery-video" / "scripts"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


render = load_module("delivery_video_render_binding", "render.py")
verify = load_module("delivery_video_verify_binding", "verify_delivery.py")

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

ISSUE = {
    "id": "BUG-123",
    "title": "Save keeps the old total",
    "severity": "major",
    "environment": "staging",
    "expected": "The new total appears after saving.",
    "actual": "The list still shows the old total.",
    "repro": ["Open the order", "Change the amount", "Save"],
}
SEGMENTS = [
    {"id": "01-repro", "phase": "repro", "shot": "screen_demo.mp4",
     "start": 0.1, "end": 0.8},
    {"id": "02-actual", "phase": "actual", "shot": "screen_demo.mp4",
     "start": 1.0, "end": 1.8},
]
TIMELINE = [
    {"id": "01-repro", "start": 0.0, "end": 1.0,
     "source": "screen_demo.mp4", "source_start": 0.1, "source_end": 0.8},
    {"id": "02-actual", "start": 1.0, "end": 2.0,
     "source": "screen_demo.mp4", "source_start": 1.0, "source_end": 1.8},
]


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe are required")
class FeedbackReportBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix="dv-feedback-binding-")
        cls.base = Path(cls.work.name) / "build"
        cls.base.mkdir()
        video = cls.base / "screen_demo.mp4"
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=1920x1080:r=30:d=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(video),
            ],
            check=True,
        )
        digest = verify.sha256(video)
        report = {
            "profile": "delivery-v1",
            "status": "pass",
            "video": "screen_demo.mp4",
            "video_sha256": digest,
            "duration_s": 2.0,
            "hard_failures": [],
            "warnings": [],
            "notices": [],
            "score": {"total": 100},
            "checks": {},
        }
        (cls.base / "quality_gate").mkdir()
        report_path = cls.base / "quality_gate" / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        (cls.base / "episode.json").write_text(
            json.dumps(
                {
                    "voice": "zh-CN-YunxiNeural",
                    "intent": "feedback",
                    "issue": ISSUE,
                    "segments": SEGMENTS,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        feedback_path = render.write_feedback_report(cls.base, ISSUE, SEGMENTS, report)
        markdown_path = render.write_feedback_markdown(
            cls.base, ISSUE, SEGMENTS, TIMELINE, report
        )
        render.bind_feedback_evidence(report_path, report, feedback_path, markdown_path)

    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()

    def copy_build(self, name: str) -> Path:
        target = Path(self.work.name) / name
        shutil.copytree(self.base, target)
        return target

    def run_verify(self, build: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify_delivery.py"), str(build)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout + result.stderr

    def edit_feedback(self, build: Path, key: str, value: str) -> None:
        path = build / "feedback.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["issue"][key] = value
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_clean_feedback_episode_passes(self):
        code, output = self.run_verify(self.copy_build("clean"))
        self.assertEqual(code, 0, output)
        self.assertIn("DELIVERY=PASS", output)

    def test_edited_title_fails(self):
        build = self.copy_build("edited-title")
        self.edit_feedback(build, "title", "TAMPERED: already fixed")
        code, output = self.run_verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("feedback report content was edited after rendering", output)
        self.assertIn("feedback.json sha256 mismatch", output)

    def test_edited_actual_fails(self):
        build = self.copy_build("edited-actual")
        self.edit_feedback(build, "actual", "TAMPERED: the new total appears")
        code, output = self.run_verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("feedback report content was edited after rendering", output)
        self.assertIn("feedback.json sha256 mismatch", output)

    def test_edited_markdown_fails(self):
        build = self.copy_build("edited-markdown")
        markdown = build / "feedback.generated.md"
        markdown.write_text(
            markdown.read_text(encoding="utf-8") + "\nTAMPERED: already fixed.\n",
            encoding="utf-8",
        )
        code, output = self.run_verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("feedback markdown was edited after rendering", output)
        self.assertIn("feedback.generated.md sha256 mismatch", output)

    def test_deleted_markdown_fails(self):
        build = self.copy_build("deleted-markdown")
        (build / "feedback.generated.md").unlink()
        code, output = self.run_verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("feedback markdown is missing: feedback.generated.md", output)


if __name__ == "__main__":
    unittest.main()
