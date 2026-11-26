import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "delivery-video" / "scripts"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
VOICE = "zh-CN-YunxiNeural"


def have_dist(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*cmd: str) -> tuple[int, str]:
    result = subprocess.run([sys.executable, "-B", *cmd], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout + result.stderr


def ffmpeg(*args: str) -> None:
    result = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *args],
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert result.returncode == 0, result.stderr


def make_take(path: Path, seconds: int = 12, pattern: str = "testsrc2") -> None:
    ffmpeg("-f", "lavfi", "-i", f"{pattern}=s=1920x1080:r=30:d={seconds}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(path))


def seed_narration(build: Path, segment: dict) -> None:
    """Pre-populate the narration cache so rendering needs no network."""
    mp3 = build / "tts" / f"{segment['id']}.mp3"
    clock = build / "tts" / f"{segment['id']}.json"
    mp3.parent.mkdir(exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame",
           "-b:a", "64k", str(mp3))
    tokens = [segment["text"][index:index + 2] for index in range(0, len(segment["text"]), 2)]
    words = [{"char": token, "start_ms": 250 + index * 500, "end_ms": 600 + index * 500}
             for index, token in enumerate(tokens)]
    clock.write_text(json.dumps({"text": segment["text"], "voice": segment.get("_voice", VOICE),
                                 "rate": segment.get("_rate", "+5%"), "words": words},
                                ensure_ascii=False), encoding="utf-8")


def write_episode(build: Path, episode: dict) -> None:
    cleaned = json.loads(json.dumps(episode, ensure_ascii=False))
    for segment in cleaned.get("segments", []):
        for key in ("_voice", "_rate"):
            segment.pop(key, None)
    (build / "episode.json").write_text(json.dumps(cleaned, ensure_ascii=False, indent=1),
                                        encoding="utf-8")


SEGMENTS = [
    {"id": "01-open", "label": "打开", "shot": "take.mp4", "start": 0.5, "end": 3.1,
     "text": "打开页面点击保存"},
    {"id": "02-readback", "label": "回读", "shot": "take.mp4", "start": 4.0, "end": 6.6,
     "text": "刷新页面结果仍然生效"},
]


def delivery_episode() -> dict:
    return {"voice": VOICE, "rate": "+5%", "layout": "fullbleed", "segments": [dict(s) for s in SEGMENTS]}


@unittest.skipUnless(FFMPEG and FFPROBE and have_dist("edge-tts") and have_dist("Pillow"),
                     "ffmpeg, ffprobe, edge-tts and Pillow are required")
class OfflineRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="dv-e2e-")
        cls.root = Path(cls._tmp.name)
        cls.build = cls.root / "screen_demo-e2e"
        (cls.build / "tts").mkdir(parents=True)
        make_take(cls.build / "take.mp4")
        cls.episode = delivery_episode()
        for segment in cls.episode["segments"]:
            seed_narration(cls.build, segment)
        write_episode(cls.build, cls.episode)
        cls.code, cls.output = run(str(SCRIPTS / "render.py"), "render", str(cls.build))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def copy(self, name: str) -> Path:
        target = self.root / name
        shutil.copytree(self.build, target)
        return target

    def test_renders_a_gated_artifact_from_cached_narration(self):
        self.assertEqual(self.code, 0, self.output)
        self.assertIn("COMPLETE", self.output)
        self.assertNotIn("Traceback", self.output)
        for name in ("screen_demo.mp4", "timeline.json", "cover.png", "quality_gate/report.json"):
            self.assertTrue((self.build / name).is_file(), name)
        report = json.loads((self.build / "quality_gate" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["hard_failures"], [])
        self.assertEqual(report["video_sha256"], sha256(self.build / "screen_demo.mp4"))

    def test_timeline_covers_every_segment_in_order(self):
        timeline = json.loads((self.build / "timeline.json").read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in timeline], ["01-open", "02-readback"])
        self.assertEqual(timeline[0]["start"], 0)
        self.assertAlmostEqual(timeline[0]["end"], timeline[1]["start"], places=3)

    def test_verify_passes_on_the_fresh_artifact(self):
        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(self.build))
        self.assertEqual(code, 0, output)
        self.assertIn("DELIVERY=PASS", output)

    def test_render_refuses_a_browser_segment_without_evidence(self):
        build = self.copy("screen_demo-noevidence")
        episode = delivery_episode()
        episode["segments"][0]["source"] = "browser"
        write_episode(build, episode)
        (build / "screen_demo.mp4").unlink()

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("FAIL:", output)
        self.assertIn("evidence", output)
        self.assertFalse((build / "screen_demo.mp4").exists())

    def test_render_rejects_a_segment_id_with_a_slash_as_a_fail_line(self):
        build = self.copy("screen_demo-slash")
        episode = delivery_episode()
        episode["segments"][0]["id"] = "a/b"
        seed_narration(build, episode["segments"][0])
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("FAIL:", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
