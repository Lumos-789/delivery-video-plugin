#!/usr/bin/env python3
"""Narration synthesis, the TTS cache and the subtitle clock."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dv_core import MAX_LINE, RenderError, check_edge_tts_version

BREAK_AFTER = set("。！？；!?;")
SOFT_BREAK = set("，、,")


def cache_files(build: Path, segment_id: str) -> tuple[Path, Path]:
    root = build / "tts"
    return root / f"{segment_id}.mp3", root / f"{segment_id}.json"


async def synth(segment: dict, voice: str, rate: str, build: Path):
    check_edge_tts_version()
    import edge_tts
    mp3, clock = cache_files(build, segment["id"])
    root = mp3.parent
    root.mkdir(exist_ok=True)
    contract = {"text": segment["text"], "voice": voice, "rate": rate}
    if mp3.exists() or clock.exists():
        if not (mp3.exists() and clock.exists()):
            raise RenderError(f"incomplete narration cache: {segment['id']}")
        cached = json.loads(clock.read_text(encoding="utf-8"))
        if any(cached.get(k) != v for k, v in contract.items()):
            raise RenderError(
                f"narration cache mismatch for {segment['id']}: edit episode.json "
                "and delete tts/<id>.mp3/.json to re-synthesize")
        return mp3, align_clock(segment["text"], cached["words"])
    words, content = [], bytearray()
    stream = edge_tts.Communicate(segment["text"], voice, rate=rate, boundary="WordBoundary")
    async for chunk in stream.stream():
        if chunk["type"] == "audio":
            content.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({"char": chunk["text"],
                          "start_ms": chunk["offset"] // 10000,
                          "end_ms": (chunk["offset"] + chunk["duration"]) // 10000})
    if not words or not content:
        raise RenderError(f"no audio or word boundaries from TTS: {segment['id']}")
    mp3.write_bytes(content)
    clock.write_text(
        json.dumps({**contract, "words": words}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return mp3, align_clock(segment["text"], words)


def align_clock(text: str, words: list[dict]) -> list[dict]:
    """Expand TTS word boundaries into character clocks using the original text.

    edge-tts WordBoundary events omit punctuation. Re-threading their timings
    through the source narration preserves commas and sentence ends so subtitle
    grouping can break where a viewer expects it to.
    """
    if not words:
        return []
    chars: list[dict] = []
    cursor = 0
    previous_end = 0
    for word in words:
        token = str(word.get("char") or "")
        if not token:
            continue
        index = text.find(token, cursor)
        if index < 0:
            raise RenderError(
                f"TTS word boundary {token!r} is not present in narration {text!r}"
            )
        gap = text[cursor:index]
        for char in gap:
            if char.isspace():
                continue
            chars.append({"char": char, "start_ms": previous_end, "end_ms": previous_end})
        if (
            any(char.isspace() for char in gap)
            and token[0].isascii()
            and token[0].isalnum()
        ):
            chars.append(
                {"char": " ", "start_ms": previous_end, "end_ms": previous_end}
            )

        start = int(word.get("start_ms") or 0)
        end = max(start + 1, int(word.get("end_ms") or 0))
        for offset, char in enumerate(token):
            char_start = round(start + (end - start) * offset / len(token))
            char_end = round(start + (end - start) * (offset + 1) / len(token))
            chars.append(
                {"char": char, "start_ms": char_start, "end_ms": char_end}
            )
        cursor = index + len(token)
        previous_end = end

    for char in text[cursor:]:
        if not char.isspace():
            chars.append(
                {"char": char, "start_ms": previous_end, "end_ms": previous_end}
            )
    return chars


def group_lines(chars: list[dict], max_line: int = MAX_LINE) -> list[list[dict]]:
    """Split word-clock chars into subtitle lines; keep latin words unbroken."""
    lines, current = [], []
    for index, char in enumerate(chars):
        current.append(char)
        nxt = chars[index + 1]["char"] if index + 1 < len(chars) else ""
        if char["char"].isascii() and char["char"].isalnum() \
                and nxt.isascii() and nxt.isalnum():
            continue
        if (char["char"] in BREAK_AFTER
                or len(current) >= max_line + 2
                or (len(current) >= max_line and char["char"] in SOFT_BREAK)):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines
