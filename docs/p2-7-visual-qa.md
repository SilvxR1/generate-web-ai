# P2.7 — Visual QA

**Question answered:** after a provider generates an image, what can we honestly
say about it before a human sees it?

Before P2.7, `AssetValidationResult` (`app.domain.creative.asset_validation`)
checked provider metadata only (a result exists, is https, has the right
count/media type, dimensions if reported) and hard-coded `visual_qa:
"not_performed"` with a fixed `not_covered` list. P2.7 adds a real
post-generation pixel layer that runs where that placeholder lived, while
keeping the metadata validator's own job (which is not pixels) unchanged.

## The one rule: not checked is never passed

Every check reports exactly one of five statuses — `pass`, `warning`, `fail`,
`not_performed`, `not_applicable` — and `not_performed`/`not_applicable` never
fold into `pass`. `ImageQAResult.overall_status` summarizes only the checks that
*ran*; `coverage` separately lists what did and did not, so a `pass` can never
be misread as "the image looks right in every respect". This is the same
discipline `NOT_COVERED_BY_METADATA_VALIDATION` already expressed for
metadata — P2.7 makes it a first-class, per-check status instead of one static
list.

## Architecture

```
provider completes → candidate has a result URL + recorded provenance
        ↓
GeneratedImageQAService.evaluate   (app.services.generated_image_qa)
        │  ArtifactFetcher (bounded https fetch, no network in tests)
        ▼
run_image_qa                       (app.domain.creative.image_qa.runner — pure)
        │  decode once (P2.6 limits reused) → 4 checks + 7 semantic placeholders
        ▼
attach_image_qa → creative_spec["visual_qa"] (provenance)
        ↓
select_direction (app.creative.critic) — a BLOCKING failure is never recommended
        ↓
create_generative_website_draft (app.publishing.drafts) — refuses a blocked direction (409 visual_qa_blocked)
        ↓
human approval / publish — unchanged
```

* `app/domain/creative/image_qa/` — the pure domain: `models.py` (statuses,
  `ImageQACheck`/`ImageQAResult`), `pixels.py` (bounded decode + CIELAB color
  math, reusing P2.6's limits and format sniffing), `checks.py` (the four
  implemented checks), `runner.py` (`run_image_qa`, the semantic seam). No
  network, storage, database or provider anywhere in this package.
* `app/creative/artifact_fetcher.py` — the network boundary: a bounded, SSRF-
  guarded https fetch of the provider's result URL (no persistent artifact
  storage exists yet — see Known limitations).
* `app/services/generated_image_qa.py` — lifecycle glue: fetch, run, attach to
  provenance, correct the metadata validator's static `visual_qa`/`not_covered`
  fields to reality.
* Provider adapters (`app.creative.higgsfield.director`) contain **no** QA
  logic — the hook lives in `director_orchestrator.orchestrate_create_directions`,
  after every candidate's provenance exists and before the critic runs, so any
  future provider gets identical QA for free.

## Implemented checks

| Check | Kind | Severity | Status if it fails |
|---|---|---|---|
| `image_integrity` | deterministic | **blocking** | fail (malformed/unsupported) or not_performed (over analysis limits) |
| `aspect_ratio` | deterministic | **blocking** | warning (≤10% off) or fail (>10% off) |
| `brand_palette_adherence` | heuristic | warning only | warning (never fails in P2.7) |
| `hero_negative_space` | heuristic | warning only | warning (never fails) |
| `unwanted_text` | semantic | informational | **not_performed** — no analyzer |
| `interface_detection` | semantic | informational | **not_performed** — no analyzer |
| `unwanted_logo` | semantic | informational | **not_performed** — no analyzer |
| `logo_distortion` | semantic | informational | **not_performed** — no analyzer |
| `subject_consistency` | semantic | informational | **not_performed** — no analyzer |
| `brand_drift` | semantic | informational | **not_performed** — no analyzer |
| `visual_artifacts` | semantic | informational | **not_performed** — no analyzer |

Only `image_integrity`/`aspect_ratio` can block; a blocking `fail` sets
`approval_eligible = false`. Nothing else can, by design, until real production
outputs justify a stricter policy.

### A. Image integrity (deterministic)
Decodes the bytes inside P2.6's exact limits (`app.domain.creative.
brand_intelligence`: ≤10 MiB, ≤8192 px/side, ≤24 MP, JPEG/PNG/WebP only, all
checked from the header before any pixel decodes). Two failure kinds are kept
apart: a **defect** (malformed/wrong format) → `fail`; hitting **our own
analysis limit** → `not_performed` (our budget is never presented as a defect
in the image).

### B. Aspect ratio (deterministic)
`|actual - expected| / expected` against `GenerationContract.output.aspect_ratio`
(read from provenance). Real Higgsfield outputs are 1696×960 for a requested
"16:9" — 0.6% off — so exact equality would be wrong.
- `≤2%` (`ASPECT_PASS_TOLERANCE`) → pass — matches the metadata validator's
  existing `_ASPECT_TOLERANCE`, so the two never disagree.
- `≤10%` (`ASPECT_FAIL_DEVIATION`) → warning — a hero crop still has real
  content (16:10 is exactly 10% off).
- `>10%` → **fail, blocking** — e.g. 3:2 is 15.6% off, portrait is ~44% off.

### C. Brand palette adherence (heuristic, never blocks)
See the dedicated section below.

### D. Negative space (heuristic, never blocks)
The scene plan's `subject_side` says which side should be visually calm. On a
≤160px thumbnail, each of the empty and subject-side regions (40% of the width
each) gets a mean *activity* score — the average absolute luminance step
between horizontally/vertically adjacent pixels (`ACTIVE_CELL_THRESHOLD = 4.0`
marks a "busy" cell). Pass requires both:
- `activity_ratio = empty / subject ≤ 0.35` (`NEGATIVE_SPACE_MAX_RATIO`) — a
  real studio backdrop measured ≈0.008–0.1 on both fixtures;
- `negative_space_active_fraction ≤ 0.15` (`NEGATIVE_SPACE_MAX_ACTIVE_FRACTION`)
  — catches a subject spilling into the "empty" side even if the average ratio
  looks fine.

**The claim is deliberately narrow and stated in the evidence
(`"claim": "... it does not detect a subject"`):** this measures relative
visual activity between image regions, nothing more. It is never worded as
"subject detected". No `subject_side` requirement (center/none/absent) →
`not_applicable`.

### Semantic checks: honestly not performed
`unwanted_text`, `interface_detection`, `unwanted_logo`, `logo_distortion`,
`subject_consistency`, `brand_drift`, `visual_artifacts` all require
*understanding* image content — OCR, an object/logo detector, a vision model.
None is implemented: no OCR, no vision model, no external/paid service. Each is
`not_performed` with `reason: "no_semantic_analyzer_configured"`, kind
`semantic`, severity `informational` — a visible coverage gap.

**The seam** (`runner.SemanticAnalyzer`, `run_image_qa(..., analyzers={...})`):
a future analyzer registers under its check name; the runner labels its result
`kind=semantic` regardless of what the analyzer reports, and an analyzer that
raises degrades to `not_performed` (`analyzer_error`) — it can never turn an
unchecked image into a passing one by failing.

**`brand_palette_adherence` ≠ `brand_drift`.** The former is a pixel
measurement against a requested color list; the latter would be a semantic
judgment of whether the image still "feels like" the brand. Conflating them
would let a coincidental color match stand in for a real semantic check —
kept as two names, one implemented, one not.

## Brand palette algorithm

Reuses P2.6's precedent (measure, don't interpret) applied in the other
direction: measuring pixels *against* a known target instead of extracting an
unknown one.

1. **Requested colors** come only from `#RRGGBB` requirements
   (`ImageQARequirements.brand_palette`, read from `scene_plan.brand_palette` in
   provenance). Any other notation (`red`, `oklch(...)`) is reported
   `unmeasurable_values`, never guessed at.
2. **Color space:** sRGB → CIELAB (D65), CIE76 (plain Euclidean) distance —
   simple, explainable, and closer to perceptual difference than raw RGB
   distance; documented as less perceptually uniform than CIEDE2000, which
   was not implemented because it would not change P2.7's conclusions and adds
   real complexity for a warning-only check.
3. **Preprocessing:** the same ≤160px thumbnail as every other check; alpha
   `<128` pixels are dropped (P2.6's cutoff), and a fully-transparent image is
   `not_performed`.
4. **Neutral handling:** a pixel with CIELAB chroma `√(a*²+b*²) < 12`
   (`NEUTRAL_CHROMA`) is neutral — it has no usable hue to compare against a
   chromatic brand color. A studio backdrop legitimately sits here; the check
   never demands the whole image be brand-colored.
5. **Per-pixel matching:** a chromatic brand color matches a pixel within
   `MATCH_CHROMATICITY_DISTANCE = 12` in the (a*, b*) plane **and**
   `MATCH_LIGHTNESS_DISTANCE = 25` in L* — wide enough that shaded/lit versions
   of the same color still count, narrow enough that a different hue at
   similar lightness does not (tested explicitly). A low-chroma brand color
   (e.g. a grey) has no hue to compare, so it instead uses plain CIE76 distance
   ≤ `MATCH_NEUTRAL_DELTA_E = 15`.
6. **Coverage / presence:** a requested color is "present" if its matching
   pixels are ≥ `MIN_PRESENCE_FRACTION = 0.5%` of analyzed pixels (~90×90px at
   1696×960 — the smallest area read as a deliberate accent, not noise).
7. **Verdict:** `pass` if at least `MIN_PRESENT_SHARE = 50%` of requested
   colors are present (a palette is a *set*; one color alone is weak evidence).
   Otherwise `warning` — **palette adherence never fails in P2.7**; it is a
   warning-only measurement until real production outputs show where a
   blocking threshold would belong.
8. **Dominant colors** (for evidence, not the verdict): 16-levels/channel
   quantization + greedy CIE76 clustering (ΔE ≤15) of the analyzed pixels,
   reported with their nearest requested brand color and its distance —
   independent of the presence test, so a low adherence result is directly
   explainable ("the image is mostly `#D1CBBD`, ΔE 26.8 from the nearest
   requested color").

Evidence recorded: `requested_palette` (per color: coverage, present, nearest
detected color + ΔE), `dominant_detected_colors`, `brand_related_pixel_fraction`,
`neutral_fraction`, `chromatic_fraction`, `analysis_pixel_count`, every
threshold used, and the color space/distance metric.

**Limitations:** a brand color low in chroma (pale cream, grey) is itself
classified neutral and can never register as "present" — documented, not
silently wrong. Coverage is measured against total analyzed pixels, not
against the subject region alone, so a large empty backdrop dilutes it
somewhat; acceptable for a warning-only check.

## Approval / recommendation policy

| Signal | Effect |
|---|---|
| A **blocking** check `fail`s (`image_integrity`, `aspect_ratio` beyond 10%) | `approval_eligible = false` |
| A **warning**-severity check warns or fails (`brand_palette_adherence`, `hero_negative_space`) | visible in `warnings`, **never blocks** |
| A semantic check is `not_performed` | visible in `coverage.not_performed`, **never blocks** |
| No `visual_qa` record at all (older row, kill switch, internal-fallback direction) | **never blocks** — absence of QA is not evidence against a candidate |

`select_direction` (`app.creative.critic`) excludes blocked candidates from
winner selection entirely — `winner` is now `CreativeDirection | None` (`None`
only when *every* candidate is blocked). A blocked candidate's
`selection_rationale` says so explicitly, distinct from "scored lower".
`create_generative_website_draft` (`app.publishing.drafts`) independently
re-checks `direction_is_approval_eligible` and refuses with a structured
`409 visual_qa_blocked` — belt-and-suspenders, since a direction can be
selected well after generation.

**Failure semantics stay separate.** The `CreativeGeneration` row and the
direction's `provider_metadata.provider` are untouched by QA — a rejected image
is still `status: "completed"`, `provider: "higgsfield"`, its real credits
charged. QA never rewrites a successful provider job as a failure; it only
gates what happens *next*.

## Provenance

`creative_spec["visual_qa"]` is the full `ImageQAResult` (version, timestamp,
overall status, eligibility, blocking reasons, warnings, coverage, the
requirements evaluated, every check with its evidence). The pre-existing
`creative_spec["validation"]["visual_qa"]`/`["not_covered"]` fields (the P2.2
metadata validator's own static placeholder) are corrected to reality by
`attach_image_qa` rather than left saying "not_performed" when QA actually ran.

No image bytes, no provider URL, no presigned URL, no credential is ever
stored — checked by dedicated tests (`test_attach_never_records_the_result_
url_or_any_credential`, etc.). No database migration: it lives in the existing
`generation_metadata` JSON column exactly as every other P2.x provenance field
does.

Example (Cositas HERO, illustrative — hex values from the real fixture run):

```json
{
  "version": "p2.7-v1",
  "overall_status": "warning",
  "approval_eligible": true,
  "blocking_reasons": [],
  "warnings": ["brand_palette_adherence: Only 0 of 3 requested brand colors have meaningful presence ..."],
  "coverage": {
    "performed": ["image_integrity", "aspect_ratio", "brand_palette_adherence", "hero_negative_space"],
    "not_performed": ["unwanted_text", "interface_detection", "unwanted_logo", "logo_distortion", "subject_consistency", "brand_drift", "visual_artifacts"],
    "not_applicable": []
  },
  "requirements": {"aspect_ratio": "16:9", "brand_palette": ["#EDB08D", "#8A6985", "#EA7D87"], "subject_side": "right", "purpose": "hero"},
  "checks": [
    {"name": "image_integrity", "status": "pass", "kind": "deterministic", "severity": "blocking", "evidence": {"format": "PNG", "width": 1696, "height": 960}},
    {"name": "aspect_ratio", "status": "pass", "kind": "deterministic", "severity": "blocking", "evidence": {"actual_ratio": 1.7667, "deviation": 0.0062}},
    {"name": "brand_palette_adherence", "status": "warning", "kind": "heuristic", "severity": "warning", "score": 0.0,
     "evidence": {"present_count": 0, "required_count": 2, "neutral_fraction": 0.926, "requested_palette": ["... see algorithm section ..."]}},
    {"name": "hero_negative_space", "status": "pass", "kind": "heuristic", "severity": "warning", "score": 0.0,
     "evidence": {"activity_ratio": 0.0, "left_region_activity": 0.004, "right_region_activity": 8.8}},
    {"name": "unwanted_text", "status": "not_performed", "kind": "semantic", "severity": "informational", "reason": "no_semantic_analyzer_configured"}
  ]
}
```

## Studio

Read-only, per direction card (`VisualQAPanel`, driven by the pure
`visualQa.ts`): an overall `Visual QA: WARNING (4/11 checks performed)` line,
each check's `Label: STATUS (heuristic)` with brief evidence, requested/
detected palette swatches (drawn only from validated `#RRGGBB` values — never
arbitrary backend text turned into CSS), and a `Not covered: …` line listing
what did not run. A blocked candidate's "Choose this direction" button is
disabled with the reason, mirroring the backend's own refusal. No
configuration UI was added.

## Fetching the artifact — a deliberate stopgap

Generated images are **not persisted** to our own storage today; the only
trace of one is the provider's own (typically short-lived) result URL on the
direction. QA therefore fetches it immediately, in the same request that
produced it, through `HttpsArtifactFetcher`: https only, no credentials in the
URL, no localhost/private/link-local/reserved/multicast IP literals, **no
redirect following**, a streaming byte cap (P2.6's `MAX_IMAGE_BYTES`), and a
timeout — never logs or returns the URL. `ArtifactFetcher` is a seam:
persisting generated artifacts to a `StorageProvider` (the durable fix) can
implement the same interface later without touching the QA domain at all.
**Known limitation:** hostnames are validated syntactically, not resolved, so
DNS rebinding is not defended against — the URL is the provider's own API
response, not user input, which bounds the real risk today.

## Resource safety

Reuses P2.6's exact image limits (no second, contradictory ceiling). Every
pixel check works on a ≤160px-longest-side thumbnail (`ANALYSIS_EDGE`, ~14k
pixels for 16:9) produced once by `decode_for_qa`, JPEG DCT-domain downscaled
before full decode where possible — never a full-resolution Python loop. A file
over the P2.6 limits is `not_performed` (a limit, not a defect); the artifact
fetcher independently caps bytes read from the network before they ever reach
the decoder.

## Also audited: pre-P2.7 approval semantics

Before P2.7, a `is_recommended` direction could always be turned into a website
draft — nothing inspected the image itself. That is exactly the gap this phase
closes; no other approval/apply/publish behavior was changed.

## Dependencies

None added. Pillow (already a P2.6 dependency) plus the standard library
(`math`, `random` only in tests). No numpy/OpenCV/ML framework/paid vision API.

## Kill switch

`VISUAL_QA_ENABLED` (default `true`). `false` restores exact pre-P2.7 behavior:
`get_generated_image_qa` returns `None`, no candidate is fetched or inspected,
no `visual_qa` key is ever added to provenance, and `validation.visual_qa`
stays the P2.2 static `"not_performed"`.

## Known limitations

* **No semantic checks are implemented** (7 of 11): text, interface/UI, logo
  presence, logo distortion, subject consistency, and brand drift all require
  understanding image content. They are `not_performed`, visibly, with a seam
  ready for a future analyzer (OCR, a vision model) — none was added in P2.7.
* **Generated images are not persisted**, so QA depends on the provider's
  result URL being reachable at generation time; a later re-check of an old
  direction cannot re-run pixel QA.
* **Palette adherence never blocks**, by design, until production data
  justifies a threshold.
* **Negative-space activity is not subject detection** — documented in the
  check's own evidence and summary wording.
* **CIE76**, not CIEDE2000 — simpler and adequate for a warning-only threshold,
  slightly less perceptually uniform at high chroma/saturation.
