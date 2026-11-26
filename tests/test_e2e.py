import hashlib
import importlib.metadata
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "delivery-video" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dv_core  # noqa: E402
import dv_episode  # noqa: E402
import dv_tts  # noqa: E402
import fake_tts  # noqa: E402
import render  # noqa: E402

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


def make_take(path: Path, seconds: int = 12, pattern: str = "testsrc2",
               size: str = "1920x1080", faststart: bool = False) -> None:
    ffmpeg("-f", "lavfi", "-i", f"{pattern}=s={size}:r=30:d={seconds}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           *(["-movflags", "+faststart"] if faststart else []), str(path))


TIME_COLORS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
               "yellow": (255, 255, 0), "magenta": (255, 0, 255), "cyan": (0, 255, 255)}


def make_time_coded_take(path: Path) -> None:
    """Six one-second color blocks plus two moving bars (so the gate sees motion): the
    color at the frame center tells which source second is on screen."""
    args = []
    for red, green, blue in TIME_COLORS.values():
        args += ["-f", "lavfi", "-i",
                 f"color=c=0x{red:02X}{green:02X}{blue:02X}:s=1920x1080:r=30:d=1"]
    chain = "".join(f"[{index}:v]" for index in range(len(TIME_COLORS)))
    ffmpeg(*args, "-filter_complex",
           f"{chain}concat=n={len(TIME_COLORS)}:v=1:a=0,"
           "drawbox=x='mod(100+t*280,1400)':y=120:w=500:h=300:color=0x808080:t=fill,"
           "drawbox=x='1300-mod(100+t*280,1400)':y=720:w=500:h=300:color=0x808080:t=fill,"
           "noise=alls=8:allf=t",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           str(path))


def center_color(build: Path, when: float) -> str:
    """Which color block sits at the center of the frame at `when` seconds."""
    from PIL import Image
    frame = build / f"probe-{when:.3f}.png"
    ffmpeg("-ss", f"{when:.3f}", "-i", str(build / "screen_demo.mp4"),
           "-frames:v", "1", str(frame))
    pixel = Image.open(frame).convert("RGB").getpixel((960, 540))
    frame.unlink()
    return min(TIME_COLORS, key=lambda name: sum((a - b) ** 2
                                                 for a, b in zip(pixel, TIME_COLORS[name])))


def seed_narration(build: Path, segment: dict, seconds: float = 2.0) -> None:
    """Pre-populate the narration cache so rendering needs no network."""
    mp3, clock = dv_tts.cache_files(build, segment["id"], segment["text"],
                                    segment.get("_voice", VOICE), segment.get("_rate", "+5%"))
    mp3.parent.mkdir(exist_ok=True)
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame",
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


def card_episode() -> dict:
    episode = delivery_episode()
    episode["segments"] = [
        {"id": "00-open", "kind": "card", "label": "交付演示", "title": "订单任务名单 2.0",
         "text": "这次交付覆盖负责人转派和空选校验。"},
        {"id": "01-open", "label": "打开", "shot": "take.mp4", "start": 0.5, "end": 7.5,
         "text": "打开页面点击保存"},
        {"id": "02-readback", "label": "回读", "shot": "take.mp4", "start": 4.0, "end": 11.0,
         "text": "刷新页面结果仍然生效"},
        {"id": "99-close", "kind": "card", "title": "两个用例全部通过，等待验收", "duration": 1.5},
    ]
    return episode


def feedback_episode() -> dict:
    return {
        "intent": "feedback", "voice": VOICE, "rate": "+5%",
        "issue": {"id": "BUG-7", "title": "保存后列表仍显示旧总额", "severity": "major",
                  "environment": "staging", "expected": "保存后立即显示新总额",
                  "actual": "列表仍是旧总额，要整页刷新才更新",
                  "repro": ["打开订单详情", "把金额改为 1200", "保存并返回列表"]},
        "segments": [
            {"id": "01-repro", "phase": "repro", "label": "复现", "shot": "take.mp4",
             "start": 0.5, "end": 7.5, "text": "照着三个步骤操作，保存后回到列表。"},
            {"id": "02-actual", "phase": "actual", "label": "现象", "shot": "take.mp4",
             "start": 4.0, "end": 6.6, "text": "列表这里仍然是旧总额。"},
            {"id": "99-impact", "phase": "impact", "kind": "card", "duration": 1.5,
             "title": "对账金额与实际不一致"},
        ],
    }


def demo_stage_episode() -> dict:
    episode = delivery_episode()
    for segment in episode["segments"]:
        segment["source"] = "demo-stage"
    return episode


def write_demo_stage_evidence(build: Path, take: Path) -> Path:
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_frames:format=duration", "-of", "json", str(take)],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    info = json.loads(probe)
    path = take.with_suffix(".evidence.json")
    path.write_text(json.dumps({
        "kind": "demo-stage-recording", "status": "passed",
        "checks": [{"id": "stage", "passed": True}],
        "capture": {"headless": True, "window_visible": False}, "scene": {"id": "save-flow"},
        "video": {"fps": 30, "frames": int(info["streams"][0]["nb_frames"]),
                  "duration_s": float(info["format"]["duration"]),
                  "sha256": sha256(take)},
    }), encoding="utf-8")
    return path


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

    def complete_review(self, build: Path, keep=None, **overrides) -> Path:
        draft = json.loads((build / "review" / "critic.draft.json").read_text(encoding="utf-8"))
        frames = [frame for frame in draft["reviewed_frames"] if keep is None or keep(frame)]
        review = dict(draft, status="pass", reviewer="second-window reviewer",
                      dimensions={name: 0.9 for name in draft["dimensions"]},
                      reviewed_frames=frames)
        review.update(overrides)
        path = build / "visual-critic.json"
        path.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def verify(self, build: Path) -> tuple[int, str]:
        return run(str(SCRIPTS / "verify_delivery.py"), str(build))

    def test_review_packet_covers_every_segment_with_three_frames(self):
        review = self.build / "review"
        self.assertEqual(sorted(path.name for path in (review / "frames").glob("*.png")),
                         ["01-open-end.png", "01-open-mid.png", "01-open-start.png",
                          "02-readback-end.png", "02-readback-mid.png", "02-readback-start.png"])
        self.assertTrue((review / "sheet_01.png").is_file())
        self.assertEqual(list(self.build.glob("preview_*.png")), [])
        draft = json.loads((review / "critic.draft.json").read_text(encoding="utf-8"))
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["video_sha256"], self.report(self.build)["video_sha256"])
        self.assertEqual([frame["segment"] for frame in draft["reviewed_frames"]],
                         ["01-open"] * 3 + ["02-readback"] * 3)
        for frame in draft["reviewed_frames"]:
            self.assertTrue((self.build / frame["frame"]).is_file(), frame["frame"])

    def test_verify_requires_a_completed_visual_review(self):
        code, output = self.verify(self.build)
        self.assertEqual(code, 1, output)
        self.assertIn("missing visual review", output)

    def test_verify_accepts_a_completed_visual_review(self):
        build = self.copy("screen_demo-reviewed")
        self.complete_review(build)

        code, output = self.verify(build)

        self.assertEqual(code, 0, output)
        self.assertIn("DELIVERY=PASS", output)

    def test_verify_rejects_a_review_that_skips_a_segment(self):
        build = self.copy("screen_demo-partial-review")
        self.complete_review(build, keep=lambda frame: frame["segment"] != "02-readback")

        code, output = self.verify(build)

        self.assertEqual(code, 1, output)
        self.assertIn("reviewed no frame inside segment 02-readback", output)

    def test_verify_rejects_a_review_that_skips_the_ending(self):
        build = self.copy("screen_demo-no-ending")
        self.complete_review(build, keep=lambda frame: not frame["frame"].endswith("-end.png"))

        code, output = self.verify(build)

        self.assertEqual(code, 1, output)
        self.assertIn("last second", output)

    def test_verify_rejects_a_review_left_pending_or_unscored(self):
        build = self.copy("screen_demo-pending-review")
        self.complete_review(build, status="pending", dimensions={}, reviewer="")
        code, output = self.verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("visual critic status is 'pending'", output)
        self.assertIn("subtitle_legibility is not scored", output)
        self.assertIn("names no reviewer", output)

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

    def edit_json(self, path: Path, change) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def report(self, build: Path) -> dict:
        return json.loads((build / "quality_gate" / "report.json").read_text(encoding="utf-8"))

    def timeline(self, build: Path) -> list:
        return json.loads((build / "timeline.json").read_text(encoding="utf-8"))

    def test_timeline_records_playback_speed_and_the_take_fingerprint(self):
        for item in self.timeline(self.build):
            self.assertEqual(item["kind"], "shot")
            self.assertAlmostEqual(item["speed"], 1.0, delta=0.05)
            self.assertEqual(item["source_sha256"], sha256(self.build / "take.mp4"))

    def test_gate_report_binds_the_episode_and_the_timeline(self):
        report = self.report(self.build)
        self.assertEqual(report["episode"],
                         {"file": "episode.json", "sha256": dv_core.content_sha256(self.episode)})
        self.assertEqual(report["timeline"]["sha256"], sha256(self.build / "timeline.json"))

    def test_delivery_note_lists_every_segment_and_is_bound(self):
        note = self.build / "delivery.generated.md"
        text = note.read_text(encoding="utf-8")
        self.assertIn("`take.mp4`", text)
        self.assertIn("1.00x", text)
        self.assertIn("00:00.000-00:02.", text)
        self.assertIn(self.report(self.build)["video_sha256"], text)
        self.assertEqual(self.report(self.build)["delivery"],
                         {"file": "delivery.generated.md", "sha256": sha256(note)})

    def test_delivery_note_carries_the_version_evidence_block(self):
        build = self.copy("screen_demo-evidence")
        episode = delivery_episode()
        episode["evidence"] = {"git_sha": "abc1234", "environment": "staging"}
        write_episode(build, episode)
        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))
        self.assertEqual(code, 0, output)
        text = (build / "delivery.generated.md").read_text(encoding="utf-8")
        self.assertIn("git_sha: abc1234", text)
        self.assertIn("environment: staging", text)

    def test_verify_fails_when_the_narration_was_edited_after_rendering(self):
        build = self.copy("screen_demo-stale-text")
        self.edit_json(build / "episode.json",
                       lambda episode: episode["segments"][1].__setitem__("text", "改掉后的旁白"))

        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("episode.json was edited after rendering", output)

    def test_verify_fails_when_a_take_was_replaced_after_rendering(self):
        build = self.copy("screen_demo-swapped-take")
        make_take(build / "take.mp4", seconds=6, pattern="smptebars")

        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("take.mp4: take changed after rendering", output)

    def test_verify_fails_when_the_timeline_was_edited_after_rendering(self):
        build = self.copy("screen_demo-stale-timeline")
        self.edit_json(build / "timeline.json",
                       lambda timeline: timeline[0].__setitem__("speed", 1.0) or
                       timeline[0].__setitem__("source_start", 9.0))

        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("timeline.json was edited after rendering", output)

    def test_verify_fails_when_the_delivery_note_was_edited_after_rendering(self):
        build = self.copy("screen_demo-edited-note")
        note = build / "delivery.generated.md"
        note.write_text(note.read_text(encoding="utf-8") + "\nEDITED\n", encoding="utf-8")

        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("delivery.generated.md was edited after rendering", output)

    def test_verify_fails_when_the_report_has_no_episode_binding(self):
        build = self.copy("screen_demo-unbound")

        def unbind(report_path: Path):
            def change(report: dict) -> None:
                report.pop("episode")
            self.edit_json(report_path, change)
        unbind(build / "quality_gate" / "report.json")

        code, output = run(str(SCRIPTS / "verify_delivery.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("no episode binding", output)

    def test_render_calls_out_clearly_retimed_segments(self):
        build = self.copy("screen_demo-retimed")
        episode = delivery_episode()
        episode["segments"][0]["end"] = 6.6
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        self.assertIn("WARN 01-open: playback", output)
        self.assertIn("fast-forwarded", output)
        speed = self.timeline(build)[0]["speed"]
        self.assertTrue(2.0 < speed < 2.6, speed)
        self.assertIn(f"{speed:.2f}x", (build / "delivery.generated.md").read_text(encoding="utf-8"))


    def test_every_speed_problem_is_reported_before_any_segment_renders(self):
        build = self.copy("screen_demo-late-slow")
        episode = delivery_episode()
        episode["segments"][1]["start"], episode["segments"][1]["end"] = 4.0, 4.3
        write_episode(build, episode)
        for stale in (build / "tts").glob("02-readback.*"):
            stale.unlink()
        for stale in (build / "tts").glob("02-readback.*"):
            stale.unlink()
        for rendered in (build / "clips").glob("01-open.*"):
            rendered.unlink()
        calls = fake_tts.fake_edge_tts(self)
        out = io.StringIO()

        with redirect_stdout(out):
            with self.assertRaises(render.RenderError) as caught:
                render.cmd_render(build)

        message = str(caught.exception)
        self.assertIn("02-readback", message)
        self.assertIn("speed", message)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("RENDERED", out.getvalue())
        self.assertFalse((build / "clips" / "01-open.mp4").exists())

    def test_preflight_reports_legacy_cache_files_once(self):
        build = self.copy("screen_demo-legacy")
        mp3 = next((build / "tts").glob("01-open.*.mp3"))
        clock = mp3.with_suffix(".json")
        (build / "tts" / "legacy-01-open.mp3").write_bytes(b"x")
        (build / "tts" / "legacy-01-open.json").write_text("{}", encoding="utf-8")

        code, output = run(str(SCRIPTS / "preflight.py"), str(build))

        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("legacy TTS cache"), 1, output)
        self.assertIn("legacy-01-open.mp3", output)
        self.assertNotIn(mp3.name, output.split("legacy TTS cache")[1])

    def test_a_corrupt_narration_cache_is_a_clean_fail(self):
        build = self.copy("screen_demo-corrupt-cache")
        mp3 = next((build / "tts").glob("01-open.*.mp3"))
        mp3.with_suffix(".json").write_text("{", encoding="utf-8")

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("FAIL:", output)
        self.assertIn("corrupt TTS clock", output)
        self.assertNotIn("Traceback", output)


    def test_fullbleed_is_the_default_layout(self):
        build = self.copy("screen_demo-default-layout")
        episode = delivery_episode()
        episode.pop("layout")
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        from PIL import Image
        frame = build / "frame.png"
        ffmpeg("-ss", "1", "-i", str(build / "screen_demo.mp4"), "-frames:v", "1", str(frame))
        image = Image.open(frame).convert("RGB")
        for column in (8, image.width - 9):
            pixel = image.getpixel((column, 540))
            distance = sum(abs(a - b) for a, b in zip(pixel, (16, 24, 43)))
            self.assertGreater(distance, 60, (column, pixel))

    def test_a_take_smaller_than_the_canvas_is_called_out(self):
        build = self.copy("screen_demo-small-take")
        make_take(build / "take.mp4", size="1280x720")

        code, output = run(str(SCRIPTS / "preflight.py"), str(build))

        self.assertEqual(code, 0, output)
        self.assertIn("1280x720 is smaller than the 1920x1080 canvas", output)


    def render_cards(self, name: str) -> tuple[Path, int, str]:
        build = self.copy(name)
        episode = card_episode()
        for segment in episode["segments"]:
            if segment.get("text"):
                seed_narration(build, segment, seconds=6 if segment.get("shot") else 2)
        write_episode(build, episode)
        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))
        return build, code, output

    def test_cards_open_and_close_the_video_and_pass_the_gate(self):
        build, code, output = self.render_cards("screen_demo-cards")

        self.assertEqual(code, 0, output)
        self.assertIn("gate=pass", output)
        timeline = self.timeline(build)
        self.assertEqual([item["kind"] for item in timeline], ["card", "shot", "shot", "card"])
        self.assertEqual(timeline[0]["title"], "订单任务名单 2.0")
        self.assertAlmostEqual(timeline[-1]["end"] - timeline[-1]["start"], 1.5, places=3)
        report = self.report(build)
        self.assertEqual([(item["start"], item["end"]) for item in report["exempt"]["intervals"]],
                         [(timeline[0]["start"], timeline[0]["end"]),
                          (timeline[-1]["start"], timeline[-1]["end"])])
        note = (build / "delivery.generated.md").read_text(encoding="utf-8")
        self.assertIn("card: 两个用例全部通过，等待验收", note)
        self.assertIn("card: 订单任务名单 2.0", note)
        self.complete_review(build)
        code, output = self.verify(build)
        self.assertEqual(code, 0, output)

    def test_attachment_gate_needs_the_timeline_to_accept_static_cards(self):
        build, code, output = self.render_cards("screen_demo-cards-gate")
        self.assertEqual(code, 0, output)
        video = build / "screen_demo.mp4"

        code, output = run(str(SCRIPTS / "render.py"), "gate", "--video", str(video),
                           "--work", str(build / "attach-plain"))
        self.assertEqual(code, 1, output)
        self.assertIn("T301", output)
        self.assertIn("--timeline", output)

        code, output = run(str(SCRIPTS / "render.py"), "gate", "--video", str(video),
                           "--work", str(build / "attach-timeline"),
                           "--timeline", str(build / "timeline.json"))
        self.assertEqual(code, 0, output)
        self.assertIn("GATE=PASS", output)


    def test_a_segment_named_like_its_take_leaves_the_take_untouched(self):
        build = self.copy("screen_demo-samename")
        episode = delivery_episode()
        shutil.copy(build / "take.mp4", build / "01-open.mp4")
        for segment in episode["segments"]:
            segment["shot"] = "01-open.mp4"
        write_episode(build, episode)
        before = sha256(build / "01-open.mp4")

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        self.assertEqual(sha256(build / "01-open.mp4"), before)
        self.assertEqual(self.timeline(build)[0]["source_sha256"], before)
        self.assertTrue((build / "clips" / "01-open.mp4").is_file())

    def test_assembly_files_cannot_collide_with_segment_ids(self):
        build = self.copy("screen_demo-reserved-ids")
        episode = delivery_episode()
        for segment, new_id in zip(episode["segments"], ("picture", "voice")):
            for stale in (build / "tts").glob(f"{segment['id']}.*"):
                stale.unlink()
            segment["id"] = new_id
            seed_narration(build, segment)
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        self.assertIn("gate=pass", output)
        self.assertEqual([item["id"] for item in self.timeline(build)], ["picture", "voice"])

    def test_a_truncated_take_fails_with_the_real_reason(self):
        build = self.copy("screen_demo-truncated")
        make_take(build / "take.mp4", faststart=True)
        data = (build / "take.mp4").read_bytes()
        (build / "take.mp4").write_bytes(data[:len(data) // 2])
        episode = delivery_episode()
        first = episode["segments"][0]
        first["start"], first["end"] = 0.5, 7.5
        for stale in (build / "tts").glob("01-open.*"):
            stale.unlink()
        seed_narration(build, first, seconds=6)
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 1, output)
        self.assertNotIn("Traceback", output)
        self.assertIn("FAIL:", output)
        self.assertIn("01-open: recording ends after", output)
        self.assertNotIn("gate=pass", output)

    def test_no_temporary_or_per_segment_files_are_left_at_the_build_root(self):
        root = sorted(path.name for path in self.build.iterdir() if path.is_file())
        self.assertEqual(root, ["cover.png", "delivery.generated.md", "episode.json",
                                "screen_demo.mp4", "take.mp4", "timeline.json"])
        self.assertTrue((self.build / "clips" / "01-open.mp4").is_file())


    def test_feedback_videos_disclose_retimed_segments_and_cards(self):
        build = self.copy("screen_demo-feedback")
        (build / "delivery.generated.md").unlink()
        episode = feedback_episode()
        for segment in episode["segments"]:
            if segment.get("text"):
                seed_narration(build, segment)
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        self.assertIn("disclosed in feedback.generated.md", output)
        self.assertNotIn("delivery.generated.md", output)
        note = (build / "feedback.generated.md").read_text(encoding="utf-8")
        speed = self.timeline(build)[0]["speed"]
        self.assertIn(f"| REPRO | 00:00.000-00:02.", note)
        self.assertIn(f"| {speed:.2f}x |", note)
        self.assertIn("01-repro plays at", note)
        self.assertIn("fast-forwarded", note)
        self.assertIn("card: 对账金额与实际不一致", note)
        self.assertNotIn("Every segment is a continuous take", note)
        self.assertFalse((build / "delivery.generated.md").exists())
        self.complete_review(build)
        code, output = self.verify(build)
        self.assertEqual(code, 0, output)

    def test_every_speed_problem_is_listed_at_once(self):
        build = self.copy("screen_demo-two-slow")
        episode = delivery_episode()
        episode["segments"][0]["start"], episode["segments"][0]["end"] = 0.5, 0.8
        episode["segments"][1]["start"], episode["segments"][1]["end"] = 4.0, 4.3
        write_episode(build, episode)
        for stale in (build / "tts").glob("*"):
            stale.unlink()
        calls = fake_tts.fake_edge_tts(self)
        out = io.StringIO()

        with redirect_stdout(out):
            with self.assertRaises(render.RenderError) as caught:
                render.cmd_render(build)

        self.assertIn("01-open", str(caught.exception))
        self.assertIn("02-readback", str(caught.exception))
        self.assertEqual(len(calls), 2)
        self.assertNotIn("RENDERED", out.getvalue())

    def test_a_clean_render_and_preflight_produce_no_warnings(self):
        self.assertEqual(self.report(self.build)["warnings"], [])
        code, output = run(str(SCRIPTS / "preflight.py"), str(self.build))
        self.assertEqual(code, 0, output)
        self.assertIn("PREFLIGHT=PASS warnings=0", output)

    def test_verify_requires_the_delivery_note_binding(self):
        build = self.copy("screen_demo-no-note-binding")
        self.complete_review(build)
        self.edit_json(build / "quality_gate" / "report.json",
                       lambda report: report.pop("delivery"))
        (build / "delivery.generated.md").unlink()

        code, output = self.verify(build)

        self.assertEqual(code, 1, output)
        self.assertIn("no delivery note binding", output)

    def test_verify_rechecks_take_evidence_with_the_render_rules(self):
        build = self.copy("screen_demo-demo-stage")
        make_take(build / "take.mp4", size="1280x720")
        evidence = write_demo_stage_evidence(build, build / "take.mp4")
        write_episode(build, demo_stage_episode())
        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))
        self.assertEqual(code, 0, output)
        self.complete_review(build)
        code, output = self.verify(build)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.timeline(build)[0]["source_evidence_sha256"], sha256(evidence))

        def window_visible(data: dict) -> None:
            data["capture"]["window_visible"] = True
        self.edit_json(evidence, window_visible)
        code, output = self.verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("window was visible", output)

        self.edit_json(evidence, lambda data: data["capture"].__setitem__("window_visible", False))
        self.edit_json(evidence, lambda data: data["video"].__setitem__("frames", "many"))
        code, output = self.verify(build)
        self.assertEqual(code, 1, output)
        self.assertNotIn("Traceback", output)
        self.assertIn("FAIL:", output)

    def test_the_visual_review_needs_passing_scores_and_real_frames(self):
        build = self.copy("screen_demo-zero-scores")
        zeros = dict.fromkeys(dv_core.DIMENSIONS, 0.0)
        self.complete_review(build, dimensions=zeros)
        code, output = self.verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("below the 0.8 pass floor", output)

        build = self.copy("screen_demo-phantom-frame")
        draft = json.loads((build / "review" / "critic.draft.json").read_text(encoding="utf-8"))
        frames = [dict(draft["reviewed_frames"][0], frame="review/frames/not-there.png")]
        self.complete_review(build, reviewed_frames=frames + draft["reviewed_frames"][1:])
        code, output = self.verify(build)
        self.assertEqual(code, 1, output)
        self.assertIn("not-there.png", output)

    def test_a_narrated_card_checks_its_cached_narration_in_preflight(self):
        build = self.copy("screen_demo-card-cache")
        episode = card_episode()
        for segment in episode["segments"]:
            if segment.get("text"):
                seed_narration(build, segment, seconds=6 if segment.get("shot") else 2)
        write_episode(build, episode)
        card = episode["segments"][0]
        clock = dv_tts.cache_files(build, card["id"], card["text"], VOICE, "+5%")[1]
        clock.write_text("{", encoding="utf-8")

        code, output = run(str(SCRIPTS / "preflight.py"), str(build))

        self.assertEqual(code, 1, output)
        self.assertIn("corrupt TTS clock", output)
    def test_playback_speed_moves_the_footage_in_the_right_direction(self):
        build = self.copy("screen_demo-speed-direction")
        make_time_coded_take(build / "take.mp4")
        episode = delivery_episode()
        fast, slow = episode["segments"]
        fast["start"], fast["end"] = 0.0, 4.0
        slow["start"], slow["end"] = 0.0, 2.0
        for stale in (build / "tts").glob("02-readback.*"):
            stale.unlink()
        seed_narration(build, slow, seconds=4)
        write_episode(build, episode)

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))

        self.assertEqual(code, 0, output)
        fast, slow = self.timeline(build)
        self.assertGreater(fast["speed"], 1.4)
        self.assertLess(slow["speed"], 0.5)
        self.assertEqual(center_color(build, 1.0), "green")
        self.assertEqual(center_color(build, fast["end"] - 0.2), "yellow")
        self.assertEqual(center_color(build, slow["start"] + 1.0), "red")
        self.assertEqual(center_color(build, slow["end"] - 0.2), "green")

    def test_verify_rejects_a_report_whose_loudness_was_never_measured(self):
        build = self.copy("screen_demo-no-loudness")
        self.complete_review(build)
        self.edit_json(build / "quality_gate" / "report.json",
                       lambda report: report["checks"].__setitem__("loudness_lufs", None))

        code, output = self.verify(build)

        self.assertEqual(code, 1, output)
        self.assertIn("loudness", output)

    def test_no_staging_or_temp_files_survive_a_failed_or_successful_render(self):
        build = self.copy("screen_demo-leftovers")
        stray = [build / "screen_demo.rendering.mp4", build / "tts" / "stray.tmp"]
        for path in stray:
            path.write_bytes(b"stale")

        def explode(raw, final):
            final.write_bytes(b"half written")
            raise render.RenderError("loudness measurement failed:\nsimulated")
        original = render.loudnorm_finalize
        render.loudnorm_finalize = explode
        try:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(render.RenderError):
                    render.cmd_render(build)
        finally:
            render.loudnorm_finalize = original
        self.assertEqual([path.name for path in build.rglob("*.tmp")], [])
        self.assertFalse((build / "screen_demo.rendering.mp4").exists())

        code, output = run(str(SCRIPTS / "render.py"), "render", str(build))
        self.assertEqual(code, 0, output)
        self.assertEqual([path.name for path in build.rglob("*.tmp")], [])
        self.assertFalse((build / "screen_demo.rendering.mp4").exists())
    def test_the_renderer_refuses_to_write_over_a_take_even_if_preflight_missed_it(self):
        build = self.copy("screen_demo-guard")
        (build / "clips" / "01-open.mp4").write_bytes(b"x")
        episode = delivery_episode()

        def source(path: Path) -> dv_episode.Source:
            return dv_episode.Source(path=path, width=1920, height=1080, duration=12.0,
                                     evidence=None)

        safe = {segment["id"]: source(build / "take.mp4") for segment in episode["segments"]}
        render.guard_outputs(build, episode["segments"], safe, VOICE, "+5%")
        sitting_on_clip = dict(safe, **{"01-open": source(build / "clips" / "01-open.mp4")})
        with self.assertRaisesRegex(render.RenderError, "refusing to render.*clips/01-open.mp4"):
            render.guard_outputs(build, episode["segments"], sitting_on_clip, VOICE, "+5%")
        other_case = dict(safe, **{"02-readback": source(build / "CLIPS" / "02-readback.mp4")})
        with self.assertRaisesRegex(render.RenderError, "refusing to render"):
            render.guard_outputs(build, episode["segments"], other_case, VOICE, "+5%")
if __name__ == "__main__":
    unittest.main()
