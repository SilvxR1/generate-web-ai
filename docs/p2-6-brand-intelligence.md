# P2.6 — Brand Intelligence

**Question answered:** how should a generated scene visually relate to the real brand?
**Not the question:** what scene to generate (P2.5 decides that and is unchanged).

Experiment 5 (P2.5) produced the intended standalone editorial still-life, but it
was visually generic because the Cositas `BrandVisualProfile` was empty (no
configured colors, and the logo was only a brand *source id*). P2.6 fills that gap
with **measured** facts — never interpreted ones.

## Principle: measured, not interpreted

| Safe (implemented) | Not safe (never inferred) |
|---|---|
| colors actually present in the official logo | "playful", "friendly", "luxurious" |
| relative luminance, light/mid/dark tone, saturation band of each color | target audience, demographics, market position |
| configured typography / visual style, carried through unchanged | a font family recognised from pixels |
| provenance of every value | symbolism of shapes or colors |

`BrandVisualProfile.semantic_analysis` stays `"not_performed"`; `mood` and `geometry`
stay empty.

## Architecture

```
Official logo (BusinessAsset, persistent storage)
        │  StorageProvider.load()   ← existing abstraction, in memory, no URL
        ▼
app.services.brand_measurement          (storage-backed, tenant-bound, never raises)
        │  BrandAssetMeasurement (hex / shares / codes — no bytes, no keys)
        ▼
CreativeBrief.brand_measurements
        ▼
build_brand_visual_profile  ── configured > measured > nothing ──► BrandVisualProfile
        ▼
plan_scenes → VisualScenePlan.brand_palette / brand_guidance   (styling only)
        ▼
GenerationContract (validated before any spend) → composer → provider prompt
```

* `app/domain/creative/brand_intelligence.py` — pure extractor. Provider-independent:
  no storage, DB, network, tenant or prompt knowledge.
* `app/services/brand_measurement.py` — the one place logo bytes are read.
* Brand Intelligence **does not choose the subject.** `VisualSubject`, `VisualIntent`
  and every non-brand `VisualScenePlan` field are provably identical with and without
  it (tests pin this for none / measured / failed / configured brand states).

## Source priority and precedence

1. Explicitly configured brand colors (`BrandConfig.colors`) — used as-is, **never mixed**
   with measured colors. When present the logo is not even read.
2. Colors measured from an authoritative official logo.
3. Nothing. No fallback identity is ever invented; the palette stays empty.

`BrandVisualProfile.palette_status` says why the palette is what it is:
`configured` · `measured` · `unavailable` (no logo / no defensible color) ·
`not_performed` (a logo exists but no measurement was supplied) · `failed`
(measurement attempted, `analysis_failure` holds a stable code).

Typography and visual style come **only** from explicit configuration
(`typography_hints`, `visual_style`) and are never read from pixels. NEW_DIRECTION
is not constrained by the existing identity, so it neither reads the logo nor emits
brand guidance.

## Palette extraction — `logo_quantization_v1`

Deterministic, pure Python, no numpy/OpenCV/LLM, ≤256px working image.

1. **Decode inside hard limits** — JPEG/PNG/WebP only (signature-sniffed, Pillow
   restricted to that one format); ≤10 MiB, ≤8192px per side, ≤24 MP, all checked from
   the header **before** any pixel is decoded.
2. **Downscale** to ≤256px with nearest-neighbour (keeps real colors).
3. **Transparency** — alpha < 128 is ignored; alpha ≥ 128 counts as opaque with its
   stored RGB (no compositing over an assumed background). A fully transparent image
   yields no colors.
4. **Flat-region filter** — only pixels whose right and lower neighbours are within 12
   per channel are counted. Anti-aliased edges and JPEG ringing are *transitions between
   colors*, not colors, so blends never become palette entries. (Falls back to all
   opaque pixels for photograph-like rasters with no flat regions.)
5. **Quantize** to 16 levels/channel; each bin keeps its mean color.
6. **Classify** by mean color: `near_white` (all channels ≥235, spread ≤20 → background,
   never a brand color), `neutral` (HSV saturation <0.15 or value <0.20: greys,
   near-black text), else `chromatic`.
7. **Cluster** greedily, largest first, merging bins within Euclidean sRGB distance 40 —
   near-duplicate shades collapse into one count-weighted mean.
8. **Select** chromatic clusters covering ≥5% of the foreground (opaque, non-near-white,
   flat pixels), at most 5, ordered by area then hex. A monochrome logo (no qualifying
   chromatic color) falls back to its qualifying neutrals. Everything else is reported
   as `excluded_colors` with a reason.

Per color: `hex`, `role` (`dominant` = largest measured area, otherwise `supporting` —
never a design-system role such as "primary CTA"), `foreground_share`, WCAG relative
`luminance`, `tone` (light/mid/dark), `saturation_band`. Warm/cool was deliberately
not added.

**Known limitations** (documented, not guessed around): a solid brand-colored
background is indistinguishable from a brand color and is kept; a pale cream/grey
brand color is classified neutral and dropped when chromatic colors exist; measured
dominance reflects area in the logo, not brand importance.

## Security and resource safety

* Reads only through `StorageProvider.load` — no new R2 path, no presigned or public
  URL, no fetching of an arbitrary `storage_url` (no SSRF surface), no temp files.
* Only an object the backend itself wrote to the **current** storage provider is read,
  and only if its key is under `<business_id>/` (the layout `generate_storage_key`
  produces): a row pointing at another business's object, a `..` traversal, an empty
  segment or a backslash is refused before any read.
* Only the (≤2) official logos are ever read — never gallery/product images.
* Bytes stay in memory, are never logged, stored or returned. Failures log a stable
  code only.
* **Non-critical by contract:** every failure (missing object, storage error, malformed,
  oversized, unsupported) is a `failed` measurement value. A failed measurement leaves
  the provider prompt **byte-for-byte identical to P2.5** (tested).

## Scene, contract, prompt

`VisualScenePlan` gains `brand_palette` (values that reached the scene) and reuses
`brand_guidance`. Measured colors are phrased as harmony guidance, not a command:

```
Brand direction: restrained palette derived from the brand colours: #EDB08D, #8A6985, #EA7D87.
```

(EVOLVE: "palette that starts from the brand colours"; configured colors keep the P2.3
wording "use exactly this colour palette…".) At most 4 measured colors reach the scene.
The sentence adds ~95 characters — the Cositas HERO prompt goes 871 → 966 — and the
prompt still contains no business name, URL, logo word, explanation, confidence or
provenance. `GenerationContract` validates that the palette is a plain color list backed
by its guidance sentence (`brand_palette_invalid` otherwise); it never requires a
reference and never changes grounding, policies or routing.

The logo remains a **brand source**, never a provider reference:
`provider_reference_asset_ids == []`, no logo bytes/URL/presigned URL leave the process,
routing stays capability-driven (Cositas HERO → `higgsfield-ai/soul/standard`).

## Provenance and Studio

`creative_spec.brand_profile` now records: `palette_status`, `palette_source`,
`palette_method`, `analysis_version`, `analysis_failure`, `measured_asset_ids`,
`measured_palette` (hex + measured properties), `excluded_colors`, whether typography /
visual style are configured, and `scene_plan.brand_palette` (which constraints reached
the scene). Hex, ids and codes only. No schema migration — it lives in the existing
`generation_metadata` JSON.

Studio shows it read-only (`Brand palette` swatches, `Palette source`, `Analysis`,
`Typography`, `Visual style`). There is no configuration UI; swatches are drawn only
from validated `#RRGGBB` values.

## Also fixed: `creative_level` audit row

`orchestrate_create_directions` hardcoded `CreativeLevel.PREMIUM` on the
`CreativeGeneration` audit row whatever the request said, contradicting the provenance
(observed in Experiment 5: request/provenance `professional`, row `premium`). It now
records `brief.creative_level`. Regression-tested for professional / cinematic / basic /
business default.

## Deferred

* Caching a measurement (e.g. in `BusinessAsset.asset_metadata`) instead of re-reading
  the logo per request (a ~3 KB read today; needs a write path, so out of scope).
* Vector logos (SVG) — unsupported by design in this version.
* Whether hex tokens in a prompt are ever rendered as visible text by the image model is
  an empirical question for the next real experiment; the prompt and contract already
  forbid generated text.
* Visual QA, OCR, semantic logo analysis — explicitly out of scope.
