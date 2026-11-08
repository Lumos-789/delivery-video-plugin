# Changelog

## 1.2.0

- **Root-caused the "only the middle of the screen is recorded" failure.** `render.py`
  used to apply a hard-coded `DEFAULT_CROP = [260, 64, 1340, 780]` to every segment
  that did not declare `crop`, silently trimming 260 px off the left and 320 px off the
  right of any full-window 1920x1080 recording (and `preflight.py` validated browser
  takes against the same silent default while demo-stage takes were validated as full
  frame — the two defaults even disagreed). Frame geometry is now opt-in everywhere:
  `crop` absent = the whole recording is shown; an explicit crop is bounds-checked
  against the real source pixels in both preflight and render and fails loud.
- New episode-level `layout` field: `banded` (default, unchanged dark-canvas look with
  the 1800x866 content box) or `fullbleed` (recording scaled onto the full 1920x1080
  canvas; 16:9 sources map 1:1; case chip stays top-left and subtitles get a dark
  backing box so they stay readable over light pages). Use `fullbleed` when every
  pixel of the screen must stay visible.
- Polyphone lint in `preflight.py`: narration containing 行/重/还/都/长/得/着/差/数/干/应/结/系/弹/屏
  produces a per-occurrence warning with context (e.g. table-row 行 háng vs walking 行
  xíng — prefer 一条/这一单), so TTS mispronunciations are caught before render instead
  of after delivery.
- Tests: `tests/test_render.py` covers full-frame default, explicit-crop placement and
  fullbleed geometry.

## 1.1.2

- Feedback reports are now fully bound to the evidence chain. `render.py` writes the
  artifact SHA256 plus, into `quality_gate/report.json`, a normalized hash of the
  `feedback.json` fields and the exact `feedback.generated.md` bytes.
- `verify_delivery.py` recomputes both hashes. Editing `issue.title`/`issue.actual` (or
  any other report field), editing the markdown, deleting the markdown, or rendering
  with an older report that has no feedback binding now fails with a specific message
  instead of `DELIVERY=PASS`. The video-side binding (artifact SHA256, truncated video,
  stripped audio, re-encoded resolution) is unchanged.
- Tests: `tests/test_feedback_binding.py` covers clean pass, edited title, edited actual,
  edited markdown and deleted markdown; `tests/test_render.py` covers canonical hash
  normalization. Feedback artifacts rendered by 1.1.1 must be re-rendered to gain the
  binding.

## 1.1.1

- Feedback/defect report mode: `intent: "feedback"` plus an `issue` block adds severity
  and phase chips, a repro-steps overlay, and writes `feedback.json` and
  `feedback.generated.md` bound to the artifact SHA256. Quality-gate rules are unchanged.

## 1.0.x (2026-10-31 → 2026-11-02)

- 1.0.0 — first ZCode release: real-recording pipeline (`preflight`/`render`/`verify`), the built-in `delivery-v1` gate, bilingual READMEs.
- 1.0.1 — narration/TTS, subtitle line-breaking and low-bitrate false-positive fixes; preflight checks render dependencies early.
- 1.0.2 — default warnings cleaned up; auditable notices kept.
- 1.0.3 / 1.0.4 — DSH runtime skill registration, then registration scoped to each Agent (plugin shell: `package.json` + `index.js` + `cordis.patch.yml`).
- 1.0.5 / 1.0.6 — desktop-environment hardening; case-driven recording guidance.
