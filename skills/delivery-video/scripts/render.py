#!/usr/bin/env python3
"""Self-contained delivery-demo renderer: episode.json -> screen_demo.mp4.

Subcommands:
  render <build-dir>                    render all segments + run the built-in gate
  gate --video <mp4> --work <dir>       run the delivery gate on any mp4 (attachment gate)

Requires: python3.9+, ffmpeg & ffprobe on PATH,
`pip install "edge-tts>=7.3.1" Pillow`.

Fail-loud by design: preflight violations, missing recordings, out-of-range speed
and gate hard failures all abort with a nonzero exit.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse
import asyncio
import bisect
import json
import math
import subprocess
import tempfile

from dv_core import (
    FPS,
    H,
    LAYOUTS,
    LEAD,
    PHASE_LABELS,
    SEVERITIES,
    SPEED_MAX,
    SPEED_MIN,
    TAIL,
    W,
    RenderError,
    check_tools,
    crop_error,
    duration,
    run,
)
from dv_draw import header, load_fonts, repro_panel, subtitle
from dv_episode import Source, validate
from dv_gate import quality_gate
from dv_notes import bind_feedback_evidence, write_feedback_markdown, write_feedback_report
from dv_tts import group_lines, synth


def segment_filter(crop: list[int] | None, layout: str, speed: float,
                   seconds: float) -> str:
    """Per-segment ffmpeg vf chain.

    crop=None shows the whole recording — frame geometry is opt-in only, so a
    missing crop can never silently hide screen edges again. "banded" fits the
    frame into the 1800x866 content box above the subtitle band; "fullbleed"
    fits it onto the full 1920x1080 canvas (16:9 sources map 1:1).
    """
    parts = []
    if crop is not None:
        x, y, w, h = crop
        parts.append(f"crop={w}:{h}:{x}:{y}")
    if layout == "fullbleed":
        box, pad = f"scale={W}:{H}", f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
    else:
        box, pad = "scale=1800:866", f"pad={W}:{H}:(ow-iw)/2:66"
    parts.append(
        f"setpts={speed}*(PTS-STARTPTS),{box}:force_original_aspect_ratio=decrease"
        f":flags=lanczos,eq=brightness=-0.035,{pad}:color=0x10182b")
    parts.append(f"fps={FPS},tpad=stop_mode=clone:stop_duration={seconds}")
    return ",".join(parts)


def narration_filter() -> str:
    return f"adelay={round(LEAD * 1000)}:all=1,apad"


def render_segment(segment: dict, source: Source, mp3: Path, chars: list[dict],
                   build: Path, feedback: dict | None = None, layout: str = "banded"):
    from PIL import Image, ImageDraw
    src = source.path
    start, end = float(segment["start"]), float(segment["end"])
    if not 0 <= start < end <= source.duration + 0.1:
        raise RenderError(f"invalid recording interval: {segment['id']}")
    seconds = math.ceil((duration(mp3) + LEAD + TAIL) * FPS) / FPS
    frames = round(seconds * FPS)
    speed = (end - start) / seconds
    if not SPEED_MIN <= speed <= SPEED_MAX:
        raise RenderError(
            f"recording speed {speed:.2f}x outside {SPEED_MIN}x..{SPEED_MAX}x for "
            f"{segment['id']}: shorten the narration or widen the interval")
    crop = segment.get("crop")
    if crop is not None:
        error = crop_error(segment["id"], crop, source.width, source.height)
        if error:
            raise RenderError(error)
    vf = segment_filter(crop, layout, seconds / (end - start), seconds)
    # stderr to temp files: an unread stderr PIPE deadlocks both ffmpegs once a log passes 64KB.
    decode_log = tempfile.TemporaryFile()
    encode_log = tempfile.TemporaryFile()
    decode = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-t", str(end - start),
         "-i", str(src), "-vf", vf, "-frames:v", str(frames),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=decode_log)
    output = build / f"{segment['id']}.mp4"
    encode = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "pipe:0", "-an", "-t", str(seconds),
         "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
         str(output)],
        stdin=subprocess.PIPE, stderr=encode_log)
    lines = group_lines(chars)
    starts = [line[0]["start_ms"] for line in lines]
    fonts = load_fonts()
    repro_steps = list((feedback or {}).get("repro") or [])
    show_repro = bool(feedback) and segment.get("phase") == "repro" and bool(repro_steps)
    case = PHASE_LABELS.get(segment.get("phase", ""), "") if feedback else segment.get("case", "")
    severity = SEVERITIES.get((feedback or {}).get("severity", ""), ("", None))
    try:
        for frame_index in range(frames):
            content = decode.stdout.read(W * H * 3)
            if len(content) != W * H * 3:
                raise RenderError(
                    f"recording decoder ended at frame {frame_index}/{frames}: "
                    "interval beyond the source")
            frame = Image.frombytes("RGB", (W, H), content)
            draw = ImageDraw.Draw(frame)
            header(draw, fonts, severity, case, segment["label"])
            if show_repro:
                repro_panel(draw, fonts, repro_steps)
            t = frame_index / FPS * 1000 - LEAD * 1000
            index = bisect.bisect_right(starts, t) - 1
            if index >= 0 and t <= lines[index][-1]["end_ms"] + 180:
                subtitle(draw, fonts, lines[index], layout)
            encode.stdin.write(frame.tobytes())
    finally:
        decode.stdout.close()
        encode.stdin.close()
        failed = decode.wait() or encode.wait()
        decode_log.seek(0)
        encode_log.seek(0)
        decode_error = decode_log.read().decode(errors="replace")
        encode_error = encode_log.read().decode(errors="replace")
        decode_log.close()
        encode_log.close()
    if failed:
        raise RenderError(f"video encoding failed:\n{decode_error}\n{encode_error}")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(mp3),
         "-af", narration_filter(), "-t", str(seconds),
         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
         str(output.with_suffix(".wav"))])
    print(f"RENDERED {segment['id']}: {seconds:.2f}s {speed:.2f}x", flush=True)
    return output, seconds


def loudnorm_finalize(raw: Path, final: Path) -> None:
    """Two-pass loudnorm (single pass drifts 1-1.5 LU); video stream copied."""
    probe = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", str(raw), "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    if probe.returncode:
        raise RenderError(f"loudness measurement failed:\n{probe.stderr[-1000:]}")
    meas = json.loads(probe.stderr[probe.stderr.rindex("{"):probe.stderr.rindex("}") + 1])
    af = ("loudnorm=I=-14:TP=-1.5:LRA=11:"
          f"measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:linear=true")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(raw), "-af", af,
         "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "192k", "-c:v", "copy", str(final)])


def cmd_render(build: Path) -> int:
    validation = validate(build)
    for note in validation.notes:
        print(f"OK {note}", flush=True)
    for warning in validation.warnings:
        print(f"WARN: {warning}", flush=True)
    if validation.errors:
        raise RenderError(
            "preflight failed; fix the material, not the thresholds:\n"
            + "\n".join(f"  - {error}" for error in validation.errors))
    episode = validation.episode
    segments = episode["segments"]
    feedback = episode.get("issue") if episode.get("intent") == "feedback" else None
    layout = episode.get("layout", "banded")
    voice, rate = episode["voice"], episode.get("rate", "+5%")

    tracks, timeline, offset = [], [], 0.0
    for segment in segments:
        mp3, chars = asyncio.run(synth(segment, voice, rate, build))
        clip, seconds = render_segment(segment, validation.sources[segment["id"]], mp3,
                                       chars, build, feedback, layout)
        tracks.append(clip)
        timeline.append({"id": segment["id"], "start": round(offset, 3),
                         "end": round(offset + seconds, 3), "source": segment["shot"],
                         "source_start": segment["start"], "source_end": segment["end"]})
        offset += seconds

    concat = build / "clips.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in tracks), encoding="utf-8")
    picture = build / "picture.mp4"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(picture)])
    voice_list = build / "voice-clips.txt"
    voice_list.write_text(
        "".join(f"file '{p.with_suffix('.wav').name}'\n" for p in tracks),
        encoding="utf-8",
    )
    voice = build / "voice.wav"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(voice_list), "-c:a", "pcm_s16le", str(voice)])
    assembled = build / "assembled.mp4"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(picture), "-i", str(voice),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-ar", "44100", "-ac", "2", "-t", str(offset), str(assembled)])
    final = build / "screen_demo.mp4"
    loudnorm_finalize(assembled, final)
    if abs(duration(final) - offset) > 0.15:
        raise RenderError(f"final duration {duration(final):.3f}s != expected {offset:.3f}s")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "2", "-i", str(final),
         "-frames:v", "1", str(build / "cover.png")])
    for index, item in enumerate(timeline):
        run(["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-ss", str((item["start"] + item["end"]) / 2), "-i", str(final),
             "-frames:v", "1", str(build / f"preview_{index:02d}.png")])
    (build / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report = quality_gate(final, build / "quality_gate")
    if feedback is not None:
        feedback_report_path = write_feedback_report(build, feedback, segments, report)
        markdown_path = write_feedback_markdown(build, feedback, segments, timeline, report)
        binding = bind_feedback_evidence(
            build / "quality_gate" / "report.json",
            report,
            feedback_report_path,
            markdown_path,
        )
        print(
            f"FEEDBACK {feedback_report_path} {markdown_path} "
            f"sha256={binding['sha256']} markdown_sha256={binding['markdown_sha256']}",
            flush=True,
        )
    print(f"COMPLETE {final} duration={duration(final):.3f}s "
          f"gate={report['status']} score={report['score']['total']}", flush=True)
    for notice in report["notices"]:
        print(f"NOTE {notice['code']}: {notice['message']}", flush=True)
    if report["status"] != "pass":
        for failure in report["hard_failures"]:
            print(f"HARD FAIL {failure['code']}: {failure['message']}", flush=True)
        return 1
    return 0


def cmd_gate(video: Path, work: Path) -> int:
    check_tools()
    if not video.is_file():
        raise RenderError(f"missing video: {video}")
    report = quality_gate(video, work)
    print(f"GATE={report['status'].upper()} video={video} "
          f"score={report['score']['total']} profile={report['profile']} "
          f"report={work / 'report.json'}", flush=True)
    for failure in report["hard_failures"]:
        print(f"HARD FAIL {failure['code']}: {failure['message']}", flush=True)
    for warning in report["warnings"]:
        print(f"WARN {warning['code']}: {warning['message']}", flush=True)
    for notice in report["notices"]:
        print(f"NOTE {notice['code']}: {notice['message']}", flush=True)
    return 0 if report["status"] == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    render_parser = sub.add_parser("render", help="render episode.json and run the gate")
    render_parser.add_argument("build", type=Path, help="build directory holding episode.json")
    gate_parser = sub.add_parser("gate", help="delivery gate for any mp4 (attachment gate)")
    gate_parser.add_argument("--video", type=Path, required=True)
    gate_parser.add_argument("--work", type=Path, required=True,
                             help="output directory for report.json")
    args = parser.parse_args()
    try:
        if args.command == "render":
            return cmd_render(args.build.expanduser().resolve())
        return cmd_gate(args.video.expanduser().resolve(), args.work.expanduser().resolve())
    except RenderError as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
