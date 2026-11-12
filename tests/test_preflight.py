import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "delivery-video" / "scripts"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe are required")
class PreflightBuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="dv-preflight-")
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_build(self, name: str, resolution: str = "1280x720") -> Path:
        build = self.root / name
        build.mkdir()
        shot = build / "stage.mp4"
        subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
             "-i", f"color=c=steelblue:s={resolution}:r=30:d=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(shot)],
            check=True,
        )
        (build / "stage.evidence.json").write_text(
            json.dumps({
                "kind": "demo-stage-recording",
                "status": "passed",
                "checks": [{"id": "stage", "passed": True}],
                "capture": {"headless": True, "window_visible": False},
                "scene": {"id": "save-flow"},
                "video": {
                    "sha256": sha256(shot),
                    "fps": 30,
                    "frames": 60,
                    "duration_s": 2.0,
                },
            }),
            encoding="utf-8",
        )
        (build / "episode.json").write_text(
            json.dumps(
                {
                    "voice": "zh-CN-YunxiNeural",
                    "rate": "+5%",
                    "segments": [{
                        "id": "s1",
                        "label": "save",
                        "text": "保存成功",
                        "shot": "stage.mp4",
                        "source": "demo-stage",
                        "start": 0.0,
                        "end": 1.9,
                    }],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return build

    def run_preflight(self, build: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "preflight.py"), str(build)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout + result.stderr

    def test_demo_stage_evidence_has_no_size_requirement(self):
        code, output = self.run_preflight(self.make_build("screen_demo"))
        self.assertEqual(code, 0, output)
        self.assertIn("PREFLIGHT=PASS", output)
        self.assertNotIn("1920x1080", output)
        self.assertNotIn("evidence size", output)

    def test_rejected_build_name_names_preflight_as_the_rejector(self):
        code, output = self.run_preflight(self.make_build("demo-videos"))
        self.assertEqual(code, 1, output)
        self.assertIn(
            "'demo-videos' is rejected by preflight (render.py itself accepts "
            "any directory name)",
            output,
        )
        self.assertNotIn("accepted by render.py", output)


if __name__ == "__main__":
    unittest.main()
