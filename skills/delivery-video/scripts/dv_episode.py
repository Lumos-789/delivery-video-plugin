#!/usr/bin/env python3
"""The one episode validator: preflight reports it and render refuses to run without it."""

from __future__ import annotations

import dataclasses
import json
import math
import re
import shutil
from pathlib import Path

from dv_core import (
    ALLOWED_SOURCES,
    DEMO_STAGE_KIND,
    EVIDENCE_KINDS,
    FPS,
    LAYOUTS,
    LEAD,
    RATE,
    SEGMENT_ID,
    SPEED_MAX,
    SPEED_MIN,
    TAIL,
    RenderError,
    check_edge_tts_version,
    check_pillow,
    crop_error,
    duration,
    feedback_errors,
    font_path,
    probe_video,
    sha256,
)
from dv_tts import cache_files

# TTS reading of these chars depends on context (e.g. 行 háng/xíng): confirm each hit or rewrite
POLYPHONES = {
    "行": "háng 表格行 / xíng 行走——表格「一行」建议改用「一条」",
    "重": "zhòng 重量 / chóng 重新、重复",
    "还": "hái 还有 / huán 归还",
    "都": "dōu 都是 / dū 首都",
    "长": "cháng 长度 / zhǎng 增长",
    "得": "dé 得到 / de 跑得快 / děi 得去",
    "着": "zhe 看着 / zháo 着急 / zhuó 着重",
    "差": "chà 差一点 / chā 差别 / chāi 出差",
    "数": "shù 数量 / shǔ 数一数",
    "干": "gàn 干活 / gān 干净",
    "应": "yīng 应该 / yìng 响应",
    "结": "jié 结果 / jiē 结实",
    "系": "xì 系统 / jì 系鞋带",
    "弹": "tán 弹出 / dàn 子弹",
    "屏": "píng 屏幕 / bǐng 屏息",
}

INTERNAL_TERMS = (
    "工作流", "管线", "pipeline", "接口", "数据库", "后端", "前端",
    "部署", "构建", "docker", "commit", "refactor",
)
AI_CLICHE_PATTERNS = (
    ("not-x-but-x cliche",
     re.compile(r"这[^。！？；\n，,]{0,4}不是[^。！？；\n]{1,40}[，,]?\s*(?:而是|是)")),
)


@dataclasses.dataclass
class Source:
    path: Path
    width: int
    height: int
    duration: float
    evidence: dict | None


@dataclasses.dataclass
class Validation:
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    notes: list[str] = dataclasses.field(default_factory=list)
    episode: dict = dataclasses.field(default_factory=dict)
    sources: dict[str, Source] = dataclasses.field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_episode(path: Path) -> dict:
    if not path.is_file():
        raise RenderError(f"missing {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RenderError("episode.json must be an object")
    return data


def load_evidence(prefix: str, path: Path, report: Validation) -> dict | None:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"{prefix}: invalid evidence JSON {path.name}: {exc}")
        return None
    if not isinstance(evidence, dict):
        report.errors.append(f"{prefix}: evidence must be an object: {path.name}")
        return None
    return evidence


def check_duration_match(prefix: str, source: Path, recorded: object, report: Validation) -> bool:
    try:
        actual = duration(source)
        recorded_s = float(recorded)
    except (RenderError, TypeError, ValueError) as exc:
        report.errors.append(f"{prefix}: evidence duration unreadable: {exc}")
        return False
    if abs(actual - recorded_s) > 0.2:
        report.errors.append(
            f"{prefix}: evidence duration {recorded_s:.2f}s != source {actual:.2f}s"
        )
    return True


def check_browser_evidence(prefix: str, source: Path, declared: bool,
                           report: Validation) -> dict | None:
    """Browser source recordings need a matching <shot>.evidence.json."""
    before = len(report.errors)
    path = source.with_suffix(".evidence.json")
    if not path.is_file():
        if declared:
            report.errors.append(
                f"{prefix}: browser shot needs {path.name}; "
                "record with a scripted browser screencast tool that writes evidence"
            )
        return None
    evidence = load_evidence(prefix, path, report)
    if evidence is None:
        return None
    kind = evidence.get("kind")
    if kind not in EVIDENCE_KINDS:
        report.errors.append(f"{prefix}: evidence kind {kind!r} is not a browser recording")
    port = evidence.get("port")
    if port is not None and (not isinstance(port, int) or isinstance(port, bool) or port <= 0):
        report.errors.append(f"{prefix}: evidence port {port!r} must be a positive integer")
    if evidence.get("sha256") != sha256(source):
        report.errors.append(f"{prefix}: evidence sha256 does not match {source.name}")
    check_duration_match(prefix, source, evidence.get("video_s"), report)
    try:
        frames = int(evidence.get("frames") or 0)
    except (TypeError, ValueError):
        frames = 0
    if frames < 1:
        report.errors.append(f"{prefix}: evidence has no captured frames")
    if len(report.errors) == before:
        report.notes.append(
            f"{prefix}: evidence kind={kind} port={port} frames={frames} "
            f"sha={str(evidence.get('sha256'))[:12]}"
        )
    return evidence


def check_demo_stage_evidence(prefix: str, source: Path, report: Validation) -> None:
    """Headless stage recording: kind=demo-stage-recording, self-checks all passed."""
    before = len(report.errors)
    path = source.with_suffix(".evidence.json")
    if not path.is_file():
        report.errors.append(
            f"{prefix}: demo-stage shot needs {path.name}; "
            "record with a headless scripted-stage tool that writes evidence"
        )
        return
    evidence = load_evidence(prefix, path, report)
    if evidence is None:
        return
    if evidence.get("kind") != DEMO_STAGE_KIND:
        report.errors.append(
            f"{prefix}: evidence kind {evidence.get('kind')!r} is not a demo-stage recording"
        )
    if evidence.get("status") != "passed":
        report.errors.append(
            f"{prefix}: demo-stage evidence status {evidence.get('status')!r} != 'passed'"
        )
    checks = evidence.get("checks")
    if not isinstance(checks, list) or not checks:
        report.errors.append(f"{prefix}: demo-stage evidence has no self-checks")
    else:
        failed = [
            str(item.get("id")) for item in checks
            if not isinstance(item, dict) or item.get("passed") is not True
        ]
        if failed:
            report.errors.append(f"{prefix}: demo-stage self-checks failed: {', '.join(failed)}")
    capture = evidence.get("capture")
    if not isinstance(capture, dict):
        report.errors.append(f"{prefix}: demo-stage evidence lacks capture block")
        capture = {}
    if capture.get("headless") is not True:
        report.errors.append(
            f"{prefix}: demo-stage recording must be headless (capture.headless=true)"
        )
    if capture.get("window_visible") is not False:
        report.errors.append(
            f"{prefix}: demo-stage window was visible; recording must not steal focus"
        )
    video = evidence.get("video")
    if not isinstance(video, dict):
        report.errors.append(f"{prefix}: demo-stage evidence lacks video block")
        return
    if video.get("sha256") != sha256(source):
        report.errors.append(f"{prefix}: evidence sha256 does not match {source.name}")
    if video.get("fps") != FPS:
        report.errors.append(f"{prefix}: demo-stage evidence fps {video.get('fps')!r} != {FPS}")
    frames = video.get("frames")
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        report.errors.append(f"{prefix}: demo-stage evidence has no captured frames")
    if check_duration_match(prefix, source, video.get("duration_s"), report) \
            and len(report.errors) == before:
        scene = evidence.get("scene")
        report.notes.append(
            f"{prefix}: demo-stage scene={(scene or {}).get('id') if isinstance(scene, dict) else None} "
            f"frames={frames} sha={str(video.get('sha256'))[:12]}"
        )


def check_evidence_size(prefix: str, evidence: dict | None, width: int, height: int,
                        report: Validation) -> None:
    """Browser/window evidence carries a size; demo-stage evidence does not."""
    if evidence is None:
        return
    if [width, height] != [1920, 1080]:
        report.errors.append(
            f"{prefix}: evidence-backed source must be 1920x1080, got {width}x{height}"
        )
    if evidence.get("size") != [width, height]:
        report.errors.append(
            f"{prefix}: evidence size {evidence.get('size')!r} != source {width}x{height}"
        )


def check_tts(build: Path, segment: dict, start: float, end: float,
              voice: str, rate: str, report: Validation) -> bool:
    """Return True when nothing is cached, so the speed is still unknown."""
    segment_id = segment["id"]
    mp3, clock = cache_files(build, segment_id)
    if not mp3.exists() and not clock.exists():
        return True
    if not mp3.is_file() or not clock.is_file():
        report.errors.append(f"{segment_id}: incomplete TTS cache, need both .mp3 and .json")
        return False
    try:
        cached = json.loads(clock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.errors.append(f"{segment_id}: invalid TTS clock JSON: {exc}")
        return False
    if not isinstance(cached, dict):
        report.errors.append(f"{segment_id}: TTS clock must be a JSON object")
        return False
    for key, value in {"text": segment["text"], "voice": voice, "rate": rate}.items():
        if cached.get(key) != value:
            report.errors.append(
                f"{segment_id}: TTS cache mismatch for {key}; "
                "delete the stale tts/<id>.mp3 and .json, then rerender"
            )
    try:
        audio_duration = duration(mp3)
    except RenderError as exc:
        report.errors.append(str(exc))
        return False
    seconds = math.ceil((audio_duration + LEAD + TAIL) * FPS) / FPS
    speed = (end - start) / seconds if seconds else 0.0
    if not SPEED_MIN <= speed <= SPEED_MAX:
        report.errors.append(
            f"{segment_id}: recording speed {speed:.2f}x outside "
            f"{SPEED_MIN:g}x..{SPEED_MAX:g}x "
            f"(interval {end - start:.2f}s, narration {seconds:.2f}s)"
        )
    return False


def check_redline(texts: list[str], report: Validation) -> None:
    for index, text in enumerate(texts, 1):
        for name, pattern in AI_CLICHE_PATTERNS:
            if pattern.search(text):
                report.errors.append(
                    f"narration {index}: AI-cliche pattern {name}; "
                    "write a plain factual statement from the viewer's perspective"
                )
        lowered = text.lower()
        for term in INTERNAL_TERMS:
            if term in lowered:
                report.warnings.append(
                    f"narration {index}: internal jargon '{term}' is fine for technical "
                    "acceptance; remove it for external deliveries"
                )


def check_polyphones(texts: list[str], report: Validation) -> None:
    for index, text in enumerate(texts, 1):
        for char, hint in POLYPHONES.items():
            pos = 0
            while True:
                pos = text.find(char, pos)
                if pos < 0:
                    break
                context = text[max(0, pos - 8):pos + 9]
                report.warnings.append(
                    f"narration {index}: polyphone '{char}' in …{context}… ({hint}); "
                    "confirm the TTS reading or rewrite to the unambiguous word"
                )
                pos += 1


def valid_evidence(evidence: dict) -> bool:
    scalar = (str, int, float)
    for key, value in evidence.items():
        if not isinstance(key, str) or not key.strip():
            return False
        if isinstance(value, list):
            if not all(isinstance(item, scalar) for item in value):
                return False
        elif not isinstance(value, scalar):
            return False
    return True


def validate_episode(build: Path, episode: dict, report: Validation) -> Validation:
    voice_value = episode.get("voice")
    rate_value = episode.get("rate", "+5%")
    voice_ok = isinstance(voice_value, str) and bool(voice_value.strip())
    rate_ok = isinstance(rate_value, str) and bool(RATE.match(rate_value))
    if not voice_ok:
        report.errors.append("voice must be a non-empty string")
    if not rate_ok:
        report.errors.append(f"rate must look like +5% or -10%, got {rate_value!r}")
    if episode.get("layout", "banded") not in LAYOUTS:
        report.errors.append(
            f"layout must be one of {sorted(LAYOUTS)}, got {episode.get('layout', 'banded')!r}"
        )
    evidence = episode.get("evidence")
    if evidence is not None and (not isinstance(evidence, dict) or not valid_evidence(evidence)):
        report.errors.append(
            "evidence must be an object of version facts (git_sha, environment, ticket ids) "
            "with string, number or list values"
        )

    segments = episode.get("segments")
    if not isinstance(segments, list) or not segments:
        report.errors.append("segments must be a non-empty array")
        return report

    seen_ids: set[str] = set()
    texts: list[str] = []
    uncached: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            report.errors.append(f"segments[{index}]: must be an object")
            continue
        segment_id = segment.get("id")
        if not isinstance(segment_id, str) or not SEGMENT_ID.match(segment_id):
            report.errors.append(
                f"segments[{index}]: id must be ASCII letters/digits/_/- and start alphanumeric"
            )
            continue
        if segment_id in seen_ids:
            report.errors.append(f"{segment_id}: duplicate id")
            continue
        seen_ids.add(segment_id)

        label = segment.get("label")
        if not isinstance(label, str) or not label.strip():
            report.errors.append(f"{segment_id}: label must be a non-empty string")
        text = segment.get("text")
        text_ok = isinstance(text, str) and bool(text.strip()) and "\n" not in text and "\r" not in text
        if not isinstance(text, str) or not text.strip():
            report.errors.append(f"{segment_id}: text must be a non-empty string")
        elif "\n" in text or "\r" in text:
            report.errors.append(f"{segment_id}: text must be one paragraph without newlines")
        else:
            texts.append(text)

        shot = segment.get("shot")
        if not isinstance(shot, str) or not shot.strip():
            report.errors.append(f"{segment_id}: shot must be a relative path")
            continue
        shot_path = Path(shot)
        if shot_path.is_absolute() or ".." in shot_path.parts:
            report.errors.append(f"{segment_id}: shot must stay inside the build directory")
            continue
        source_kind = segment.get("source")
        if source_kind is not None and source_kind not in ALLOWED_SOURCES:
            report.errors.append(
                f"{segment_id}: source must be one of {sorted(ALLOWED_SOURCES)}, got {source_kind!r}"
            )
            continue
        source = (build / shot_path).resolve()
        try:
            source.relative_to(build)
        except ValueError:
            report.errors.append(f"{segment_id}: shot resolves outside the build directory")
            continue
        if not source.is_file() or source.stat().st_size == 0:
            report.errors.append(f"{segment_id}: missing or empty recording {source}")
            continue
        if source_kind == "demo-stage":
            check_demo_stage_evidence(segment_id, source, report)
            evidence = None
        else:
            evidence = check_browser_evidence(segment_id, source, source_kind == "browser", report)

        start = segment.get("start")
        end = segment.get("end")
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not isinstance(end, (int, float)) or isinstance(end, bool)):
            report.errors.append(f"{segment_id}: start and end must be numbers")
            continue
        if start < 0 or end <= start:
            report.errors.append(
                f"{segment_id}: require 0 <= start < end, got {start}..{end}"
            )
            continue
        try:
            width, height, source_duration = probe_video(source)
        except RenderError as exc:
            report.errors.append(str(exc))
            continue
        report.sources[segment_id] = Source(source, width, height, source_duration, evidence)
        check_evidence_size(segment_id, evidence, width, height, report)
        if end > source_duration + 0.1:
            report.errors.append(
                f"{segment_id}: interval ends at {end:.2f}s beyond source duration "
                f"{source_duration:.2f}s"
            )
            continue
        crop = segment.get("crop")
        if crop is not None:
            error = crop_error(segment_id, crop, width, height)
            if error:
                report.errors.append(error)
        report.notes.append(
            f"{segment_id}: {shot} {start:.2f}-{end:.2f}s "
            f"source={width}x{height} duration={source_duration:.2f}s"
        )
        if voice_ok and rate_ok and text_ok:
            if check_tts(build, segment, float(start), float(end),
                         voice_value, rate_value, report):
                uncached.append(segment_id)

    report.errors.extend(feedback_errors(episode, segments))
    if texts:
        check_redline(texts, report)
        check_polyphones(texts, report)
    if uncached:
        report.warnings.append(
            f"{len(uncached)} segment(s) have no cached TTS; speed range not checked: "
            + ", ".join(uncached)
        )
    return report


def validate(build: Path) -> Validation:
    """Every material rule for a build directory, collected instead of raised."""
    report = Validation()
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            report.errors.append(f"{executable} is not on PATH")
    for check in (check_edge_tts_version, check_pillow, font_path):
        try:
            check()
        except RenderError as exc:
            report.errors.append(str(exc))
    if not build.is_dir():
        report.errors.append(f"missing build directory: {build}")
        return report
    if any(error.endswith("is not on PATH") for error in report.errors):
        return report
    try:
        report.episode = load_episode(build / "episode.json")
    except RenderError as exc:
        report.errors.append(str(exc))
        return report
    return validate_episode(build, report.episode, report)
