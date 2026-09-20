# P2.3 — Brand intelligence, reference strategy and model routing

> **Follow-up: P2.4.** Experiment 3 confirmed the routing here worked (no logo, no reference) but exposed that the
> business description reaching the prompt made the model draw a webpage. See
> [p2-4-creative-context-visual-intent.md](p2-4-creative-context-visual-intent.md).

## Why

Two real production generations with `higgsfield-ai/soul/reference` and the official Cositas y Puntos logo as the
reference (P2.1 and P2.2) both recreated the logo and rendered the business name — even after P2.2 removed the name
from the prompt and marked the logo as *identity guidance*. The text came from what the model **saw**, not from what we
**said**. Marking an asset `IDENTITY` in our own domain does not change the pixels a reference-conditioned model
receives.

The consequence, encoded in P2.3: **a `BusinessAsset` is not a `GenerationReferenceAsset`.** Having an asset does not
mean the provider should receive it, and being *authoritative* does not mean "always send it".

## Architecture

```
BusinessAssets ──► BrandVisualProfile     (identity as text: palette / style / sources)
      │
      └──────────► GenerationReferenceStrategy   (which assets MAY go to a model; which never do)
                          │
CreativeGenerationSpec ───┴──► GenerationPlan ──► CreativeGenerationRequirements
                                                        │
                                       CreativeModelRouter  (capability-based; picks a registered model)
                                                        │
                                          Higgsfield adapter (payload, R2 presign, polling, errors)

REAL LOGO BusinessAsset ─────► deterministic website/UI rendering   (never recreated by an image model)
```

| Module | Role |
| --- | --- |
| `app/domain/creative/brand_profile.py` | `BrandVisualProfile` |
| `app/domain/creative/reference_strategy.py` | `decide_reference_strategy` |
| `app/domain/creative/model_routing.py` | capabilities, requirements, `select_model` |
| `app/domain/creative/planning.py` | `GenerationPlan` (spec + profile + strategy + requirements) |
| `app/creative/higgsfield/api_client.py` | model registry with capabilities, `registered_models()` |
| `app/creative/higgsfield/director.py` | adapter: routes, resolves references, translates, runs, records |

Everything except the adapter is pure domain code (no network, R2, SDK or database).

## Higgsfield capabilities (verified against the official OpenAPI spec)

Source: `https://docs.higgsfield.ai/docs/openapi.json` (v2.0.0), fetched read-only; no generation call.

| Model | Status | What is established |
| --- | --- | --- |
| `higgsfield-ai/soul/standard` | **verified — current official spec** | Prompt-only text-to-image. Body: `prompt` (required), `num_images`, `resolution` (2K/4K), `aspect_ratio` (1:1, 4:3, 3:4, 3:2, 2:3, 5:4, 4:5, 16:9, 9:16, 21:9). **No reference input.** The only image model in the current spec. Not yet exercised in production. |
| `higgsfield-ai/soul/reference` | **verified — observed in production** | Requires exactly one `image_reference_url`. Absent from the current published spec, but completed two real generations on this workspace. |
| `nano-banana` | **earlier spec only** | Optional `input_images` (0–8). Absent from the current spec; 404 `model_not_found` on this workspace. Registered, never preferred. |
| video models (`kling-video/*`, `minimax/*`) | not relevant | Video outputs; out of scope for image generation. |

Unknown (deliberately left unknown, `None`): which reference **roles** any model handles well, and per-purpose
suitability. Nothing here claims `soul/standard` produces good hero imagery — only that it can generate without a
reference.

## BrandVisualProfile

Built only from what is reliably known: structured brand configuration (colors, visual style, typography) plus the ids
of the official-logo assets it came from. `geometry` and `mood` stay empty and `semantic_analysis` is always
`"not_performed"`: there is no image understanding in this backend, and nothing infers "playful" or "luxury" from
pixels. Palette values are sanitized before they can reach a prompt.

**Palette extraction is designed for but deferred.** `build_brand_visual_profile(..., asset_palettes=...)` and
`PaletteSource.ASSET_EXTRACTION` are the seam. It was not wired because: Pillow is not a dependency and production
installs from a frozen `uv.lock` (a dependency change already broke a Railway boot once, #17); it needs a storage read
in the request path; and derived palettes would need somewhere to be persisted. Consequence: a business with no brand
colors configured gets an empty palette, and the prompt says so ("no verified brand palette … do not assume one")
instead of inventing one.

## Reference strategy

| Purpose | Provider reference | Notes |
| --- | --- | --- |
| HERO, BACKGROUND, TEXTURE | none | identity reaches the model as text only |
| SECTION, EDITORIAL | optional `STYLE` reference from real photography | never for `NEW_DIRECTION`; never team photos or unclassified assets |
| PRODUCT | **required** `PRODUCT` reference from a real product image | with none: unsatisfiable — never invents a product |

Always withheld: the official logo (a brand source only), non-image assets, `LOW_QUALITY` and previously generated
assets. Unavailable assets never reach the brief. The strategy records a reason code for every withheld asset.

**Authoritative assets** (real, non-generated, not low quality) must not be silently replaced or falsified. That is all
it means. The real logo is rendered by the website layer; a generated hero that needs the logo visible should be
generated background + real logo overlay + HTML text. **That overlay is not implemented here** (deferred to website
generation).

## Model router

Requirements (output, aspect ratio, text policy, required/optional reference count) are derived from the spec and the
strategy. Each registered model declares capabilities (`supports_reference`, `requires_reference`,
`max_reference_images`, `supported_aspect_ratios`, `reference_roles`, `verified_by`). The router picks a model whose
capabilities satisfy the requirements — there is no `if hero: model = "..."`.

- `HIGGSFIELD_API_MODEL` is now a **preference**: chosen when it satisfies the requirements, otherwise another
  registered model is selected and the reason is recorded.
- Ties prefer better-verified models (`current_official_spec` > `observed_in_production` > `earlier_official_spec`).
- A model that requires a reference is never selected for a request with none — the exact P2.1/P2.2 failure.
- If nothing satisfies the requirements: `HiggsfieldNoSuitableModelError` (a `HiggsfieldModelUnavailableError`
  subclass), raised **before any spend**.

For the Cositas HERO request that produced the experiments, production configuration
(`HIGGSFIELD_API_MODEL=higgsfield-ai/soul/reference`) now routes to `higgsfield-ai/soul/standard` with no reference.

## Fallback and errors

`FallbackCreativeDirector` degrades to `InternalCreativeDirector` for `HiggsfieldNoSuitableModelError` with
`fallback_reason: higgsfield_no_suitable_model` and `fallback_detail` (`no_registered_model_satisfies_requirements` or
`product_reference_missing`). The internal result is tagged `internal_fallback` and never presented as a generated
image; its provenance states `generated_image: false` and that nothing was sent to a model. Without the wrapper the
route returns 422 `higgsfield_no_suitable_model`. Budget, one-submission-per-request behaviour, structured provider
errors and R2 presigning (only for a reference that is actually selected) are unchanged.

## Provenance

`generation_metadata.creative_spec` (no migration) now distinguishes:

- `brand_source_asset_ids` — assets that informed the brand profile;
- `provider_reference_asset_ids` — assets actually sent to the image model.

Example for the Cositas regression: `brand_source_asset_ids: [<logo>]`, `provider_reference_asset_ids: []`. Also
recorded: `brand_profile` (version, sources, palette, `semantic_analysis`), `reference_strategy` (policy, withheld ids and
reasons), `model_selection` (selected, reason, requirements, rejected models and why), prompt version/fingerprint and
validation. Never stored: presigned URLs, credentials, prompt text, the business name.

## Backward compatibility

`{"hard_limit": 2.0}` still works (HERO by default). It no longer pushes the logo through `soul/reference`; when no
model can honestly satisfy a request the response is an explicit, labelled fallback rather than a recreated logo.
`develop_direction` continues from the previous *generated* image on a reference-capable model (never the logo) and is
skipped safely if none exists.

## Deferred

- Palette extraction from logo bytes (interface exists; see above).
- Semantic brand analysis (mood/geometry) — needs a real analysis mechanism.
- Deterministic real-logo overlay in website generation.
- Production validation of `soul/standard` output quality and entitlement (it is verified as an endpoint, not as a good
  hero generator).
- Real provider cost accounting: `estimated_generation_units` remains an internal estimate — not Higgsfield credits and
  not USD. Both real experiments cost about $0.06 against an internal estimate of 2.0.
- Visual QA for unwanted text, logo distortion and brand drift.
