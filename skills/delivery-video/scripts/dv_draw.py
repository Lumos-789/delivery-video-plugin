#!/usr/bin/env python3
"""Frame furniture: header chips, the repro panel and subtitles."""

from __future__ import annotations

import dataclasses

from dv_core import REPRO_PANEL_LIMIT, W, find_font

SUBTITLE_Y = 1008


@dataclasses.dataclass
class Fonts:
    subtitle: object
    label: object
    case: object
    panel: object
    panel_head: object


def load_fonts() -> Fonts:
    return Fonts(find_font(48), find_font(32), find_font(30), find_font(24), find_font(18))


def header(draw, fonts: Fonts, severity: tuple, case: str, label: str) -> None:
    """Top-left chips: severity (feedback), case or phase, then the free label."""
    x = 82
    if severity[1] is not None:
        right = 56 + draw.textlength(severity[0], font=fonts.case) + 28
        draw.rounded_rectangle((56, 12, right, 56), radius=8, fill=severity[1])
        draw.text((70, 34), severity[0], font=fonts.case, fill="white", anchor="lm")
        x = right + 12
    if case:
        right = x + draw.textlength(case, font=fonts.case) + 28
        draw.rounded_rectangle((x - 4, 12, right, 56), radius=8, fill=(37, 99, 235))
        draw.text((x + 10, 34), case, font=fonts.case, fill="white", anchor="lm")
        x = right + 12
    draw.text((x, 34), label, font=fonts.label, fill=(190, 206, 230), anchor="lm")


def repro_panel(draw, fonts: Fonts, steps: list) -> None:
    visible = steps[:REPRO_PANEL_LIMIT]
    omitted = len(steps) - len(visible)
    width, line_h = 520, 34
    height = 62 + line_h * len(visible) + (line_h if omitted else 0) + 10
    right, top = W - 56, 92
    left = right - width
    draw.rounded_rectangle((left, top, right, top + height), radius=10, fill=(16, 26, 46))
    draw.text((left + 18, top + 22), "REPRO STEPS", font=fonts.panel_head,
              fill=(150, 176, 214), anchor="lm")
    y = top + 52
    for index, step in enumerate(visible):
        text = f"{index + 1}. {step}"
        if len(text) > 34:
            text = text[:33] + "..."
        draw.text((left + 18, y), text, font=fonts.panel, fill=(236, 242, 250), anchor="lm")
        y += line_h
    if omitted:
        draw.text((left + 18, y), f"+{omitted} more", font=fonts.panel_head,
                  fill=(150, 176, 214), anchor="lm")


def subtitle(draw, fonts: Fonts, line: list, layout: str) -> None:
    text = "".join(char["char"] for char in line)
    if layout == "fullbleed":
        width = draw.textlength(text, font=fonts.subtitle)
        draw.rounded_rectangle(
            ((W - width) / 2 - 26, SUBTITLE_Y - 34, (W + width) / 2 + 26, SUBTITLE_Y + 34),
            radius=12, fill=(16, 24, 43))
    draw.text((W / 2, SUBTITLE_Y), text, font=fonts.subtitle, fill="white", anchor="mm")
