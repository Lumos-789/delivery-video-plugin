# Changelog

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
