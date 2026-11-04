# Episode, takes and review details

## episode.json fields

`render.py render <build>` reads `<build>/episode.json`. Build directories are named `screen_demo` or `screen_demo-<slug>`.

| Field | Required | Notes |
| --- | --- | --- |
| `voice` | yes | edge-tts voice, e.g. `zh-CN-YunxiNeural`, `en-US-AndrewNeural` |
| `rate` | no | speech rate, default `+5%`, format `+N%` or `-N%` |
| `title` | no | internal identification only |
| `intent` | no | `delivery` (default) or `feedback`; feedback requires the `issue` block |
| `issue` | for feedback | defect report metadata, see below |
| `segments` | yes | non-empty array, unique `id`s |
| `segments[].id` | yes | ASCII id, e.g. `01-entry` |
| `segments[].case` | no | acceptance-case chip shown top-left, e.g. `D-02`; recommended when the video covers 2+ cases |
| `segments[].phase` | for feedback | `context`, `repro`, `actual`, `expected` or `impact`; becomes the second chip |
| `segments[].label` | yes | short top-left label, 2–10 chars |
| `segments[].shot` | yes | recording file relative to the build directory |
| `segments[].start` | yes | range start in the source, seconds |
| `segments[].end` | yes | range end, must exceed start |
| `segments[].source` | no | `browser` requires `<shot-stem>.evidence.json`; `demo-stage` requires headless-stage evidence; window recordings may say `window` or omit |
| `segments[].crop` | no | `[x, y, w, h]` in source pixels, default `[260, 64, 1340, 780]` |
| `segments[].text` | yes | one continuous narration line, no newlines; subtitles auto-break at punctuation |

### Feedback issues

`intent: "feedback"` turns the artifact into a defect report while keeping the same recording and gate rules.

| Field | Required | Notes |
| --- | --- | --- |
| `issue.title` | yes | one sentence naming the wrong behaviour |
| `issue.severity` | yes | `blocker`, `critical`, `major` or `minor` |
| `issue.expected` | yes | what a correct build must show |
| `issue.actual` | yes | what this build actually shows |
| `issue.id` | no | ticket or case id |
| `issue.environment` | no | build, environment, account or data |
| `issue.repro` | no | up to 12 steps, one string per step |

At least one segment must use `phase: "actual"`. `render.py` writes `feedback.json` with the
issue, the segment phases and the artifact SHA256; `verify_delivery.py` treats a missing or
misbound report as a failure. Delivery episodes without `intent` keep the original contract.

During `phase: "repro"` segments the renderer also draws the first five `issue.repro` steps in
the top-right corner; the full list stays in the generated markdown. A `phase` on a delivery
episode is rejected, so the two modes cannot be mixed by accident.

### Generated feedback files

| File | Contents |
| --- | --- |
| `feedback.json` | machine-readable issue, segment phases and artifact SHA256; bound to the gate report |
| `feedback.generated.md` | ticket-ready draft: expected/actual, numbered repro steps, per-segment in-video timing and source range, artifact hash and gate result |

`feedback.generated.md` is rewritten on every render — edit a copy or keep additions in a
separate note. The draft deliberately does not claim a fix, a root cause or coverage of other
environments.

### Case list (recommended, not enforced)

For a multi-case delivery, note the cases before recording and reuse the same ids everywhere (take names, `episode.json`, the delivery note). Keep this list in the target project with its build directory and delivery note; the plugin itself stays self-contained. A background block plus a compact table is enough:

```text
Feature: <what it is>
Audience: <who uses it>
Problem this demo covers: <one sentence>
```

| Case | Proves | Entry | Precondition / data | Expected observable result | Result |
| --- | --- | --- | --- | --- | --- |
| F-01 | first flow works end to end | page or command | test account/order | what the viewer must see | PASS |
| F-02 | second flow / edge case | page or command | reset or separate data | what the viewer must see | PASS / FAIL / OBS |

One row is one real run. Give its takes case-prefixed filenames and map them to segments with the same `case` id. The background block can feed the opening narration; it is a suggestion, not a required episode field. Preflight does not require this structure — it is a working aid, not a contract.

### Choosing time ranges

- Leave 0.3–0.8s before the action starts so the entry reads.
- Success feedback, read-back and key states must fall inside the range.
- The last segment must be a result, not a waiting state.
- A stretch of static frames longer than ~8s inside a take means cut it: idle time makes the whole video feel stuck (the gate's `T301`/`T304` enforce this).
- You may cut waiting gaps, but never merge pieces of different runs into one success.
- Playback speed lands between 0.3x and 3x by construction; below 0.3x the action is too slow or the narration too short, above 3x the narration overruns the range — split or trim instead of forcing.
- Aim for 15–35 characters per narration segment; important results get their own segment.
- In a multi-case video, keep one result segment per case and follow the execution order, so the viewer can tell where one case ends and the next begins.

### Browser recording evidence

Browser segments (recorded by a scripted screencast tool) carry `<shot-stem>.evidence.json` (`take-01.mp4` → `take-01.evidence.json`). Preflight checks:

- `kind` is `cdp-screencast` or `browser-demo`; `port`, when present, is a positive integer;
- `size` is `[1920, 1080]` and `sha256` matches the current mp4; `video_s` is within 0.2s of the measured duration; `frames` ≥ 1;
- a `source: "browser"` segment without evidence fails immediately.

### Demo-stage evidence

Segments with `source: "demo-stage"` come from a headless scripted-stage tool. The evidence must show `kind: "demo-stage-recording"`, `status: "passed"`, all self-checks passed, `capture.headless: true`, `capture.window_visible: false`, and a `video` block with matching sha256/fps/frames/duration. A visible window during recording fails — the stage must not steal focus.

### TTS cache contract

Narration is cached at `tts/<segment-id>.mp3` + `tts/<segment-id>.json`. The clock JSON records `{text, voice, rate, words[]}`; changing any of them without deleting the cache files fails the render with a mismatch. Editing narration = delete that segment's two cache files and re-render.

## visual-critic.json

An independent visual review, ideally by a second model or reviewer who has not seen the maker's conclusions. Schema:

```json
{
  "status": "pass",
  "critical": [],
  "dimensions": {
    "subtitle_legibility": 0.96,
    "subtitle_safe_margins": 0.98,
    "interface_legibility": 0.9,
    "composition": 0.92,
    "business_content_alignment": 0.97
  },
  "reviewed_frames": [
    {"time_s": 1.0, "scene": "entry"},
    {"time_s": 8.0, "scene": "key action"},
    {"time_s": 16.0, "scene": "result read-back"}
  ],
  "observations": [
    "Subtitles complete; no controls covered.",
    "Success message matches the narration."
  ],
  "limitations": [
    "Static frames only; does not prove full click ordering or database consistency."
  ],
  "reviewer": "independent-review",
  "video_sha256": "<artifact SHA256>"
}
```

`video_sha256` must match the current artifact, otherwise the review binds to nothing.

## Reading the quality report

`quality_gate/report.json` (`profile: delivery-v1`) — the important parts:

- `status` is `pass` and `hard_failures` is empty.
- `score.total` plus the per-check details; don't judge by the total alone.
- `warnings` — actionable anomalies such as `E301` (long silence); keep them visible.
- `notices` — advisory measurements such as `M111` low bitrate density. They do not reduce the score; inspect text at 1:1.
- `E401` is enforced only when `verify_delivery.py --require-critic` is requested for an external delivery.

The gate binds to the artifact via `video_sha256`; after any re-render the gate re-runs automatically with `render.py render`. For an attachment gate on an arbitrary mp4, run `render.py gate --video <mp4> --work <dir>` — it writes its own report.

## delivery.md template

````markdown
# <Feature> delivery demo

## Running version

- Environment: <env>
- Frontend/backend/local version: <SHA or release>
- Verification entry: <probe/start command>

## Real evidence

- <ticket/request id/page read-back/db bounds>
- The video covers <page operations>; <database consistency/concurrency/full regression> is covered by <evidence>.

## Case results (optional, recommended for multi-case videos)

| Case | Result | Evidence | Video range |
| --- | --- | --- | --- |
| <F-01> | PASS / FAIL / OBS | <take or page evidence> | <start–end in the artifact> |

## Artifact

- File: <absolute path>
- Duration/resolution/fps/codec: <...>
- SHA256: <...>
- Recipe: <episode.json absolute path>
- Takes: <directory>
- Gate: <report.json absolute path>, PASS, <score>
- Attachment gate: <report for the posted file>, PASS, profile delivery-v1, uploaded SHA256 <...>
- Visual review: <visual-critic.json path or "not performed">

## Commands actually run

```bash
<key recording/render/gate commands>
```

## Boundaries

- Proven: <...>
- Not proven: <...>

## Status

Awaiting user review — not uploaded / not published.
````

## Common failures

| Symptom | Fix |
| --- | --- |
| `missing real recording` | `shot` path wrong or file not in the build directory |
| `invalid recording interval` | `start/end` beyond the source, or the cut lands mid-action |
| `recording speed outside 0.3x..3x` | shorten narration, widen the range or split the segment |
| Large black areas in a take | window off-screen or occluded during recording; re-record |
| Subtitles clipped or covering controls | adjust `crop` or shorten the narration |
| Gate hard failure | open `report.json`, fix the material per the highest-severity item; never touch thresholds |
| `M111` low bitrate notice | inspect text at 1:1; sparse static pages can legitimately compress below 1000 kbps. Re-record or re-encode only if text smears |
| `T301`/`T304` freeze-heavy | cut waiting ranges, raise range speed, add a real interaction |
| Final duration mismatch | re-render from scratch; do not trim the artifact by hand |
| Portrait need | this pipeline is 16:9 landscape by design; use a portrait-dedicated recipe instead of hard-cropping |
