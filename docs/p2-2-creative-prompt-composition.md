# P2.2 — Creative direction and prompt composition

> **Superseded in part by P2.3.** Real generations showed that marking a logo `IDENTITY` does not stop a
> reference-conditioned model recreating it. Reference *selection* now lives in
> `app/domain/creative/reference_strategy.py` and the official logo is never sent to a model — see
> [p2-3-brand-reference-model-routing.md](p2-3-brand-reference-model-routing.md). Composition, text policy, validation
> and provenance described below still apply.

## Why

The first real production Higgsfield generation (`higgsfield-ai/soul/reference`, real Cositas y Puntos logo as the
reference) worked technically but produced an unusable web asset: the model *recreated the logo*, left large unused
areas, and hallucinated text, including the business name. The lesson: **the reference asset is not the output
intent.** A logo should constrain identity, palette, shapes and mood — not mean "redraw this".

P2.2 adds a provider-independent layer between business context and any provider adapter, so that creative strategy
never lives inside `HiggsfieldApiCreativeDirector`.

## Layers

```
CreativeBrief (verified facts + brand mode + level + purpose)
   → CreativeGenerationSpec           app/domain/creative/spec.py
       purpose, brand_mode, creative_level, text_policy,
       ranked reference_assets (id + usage), output requirements
   → CreativePromptComposer           app/domain/creative/prompt_composer.py
       ComposedCreativePrompt: positive prompt, negatives, reference /
       composition / output instructions, verified facts vs interpretation
   → provider adapter                 app/creative/higgsfield/{director,translation}.py
       reference → URL, model limits, aspect ratio, payload, polling, errors
   → validation + provenance          app/domain/creative/{asset_validation,provenance}.py
```

Everything above the adapter is pure (no network, R2, provider SDK or database) and unit-tested in isolation.

Existing vocabulary is reused, not duplicated: **brand mode is `BrandStrategy`** (`PRESERVE` / `EVOLVE` /
`NEW_DIRECTION`) and the level is `CreativeLevel`. The only new enums are `AssetPurpose`, `ReferenceUsage` and
`TextPolicy`.

## Asset purpose

`HERO`, `SECTION`, `BACKGROUND`, `PRODUCT`, `EDITORIAL`, `TEXTURE`. Purpose changes composition rules (e.g. HERO
reserves negative space for the real HTML heading/CTA; BACKGROUND has no central subject and clear contrast zones;
TEXTURE is seamless with no focal subject), the aspect ratio, and reference ranking. `SOCIAL`/`DECORATIVE` were
deliberately not added: nothing in the product uses them yet.

## Reference usage

Each reference carries *why* it is supplied: `IDENTITY`, `PALETTE`, `STYLE`, `SUBJECT`, `PRODUCT`, `COMPOSITION`.
A logo is `IDENTITY` (or `PALETTE` for backgrounds, textures and `NEW_DIRECTION`), never the subject. For a `PRODUCT`
purpose, real product imagery outranks the logo. Only image assets qualify; `LOW_QUALITY` assets are excluded unless
they are the logo; unavailable assets never reach the brief; real assets outrank generated ones.

Selection is deterministic and ranked; the adapter resolves candidates in order, skips any it cannot resolve, and
sends only as many as the model allows (`soul/reference`: exactly one). The composed prompt describes only the
references actually sent.

## Text and logo policy

Default and only policy today: `NO_GENERATED_TEXT`. The prompt forbids words, letters, captions, slogans, watermarks,
signatures, fake logos and UI text. The business name is **not** sent to the provider (and is scrubbed from free-text
facts), because naming it invites the model to render it. Headings, names, CTAs and prices belong to HTML/CSS.

The real logo is authoritative: it guides palette, geometry and brand character and is never recreated. If the design
needs the logo visible, the website overlays the real `BusinessAsset` logo.

## Facts vs interpretation

The business-context section states only facts present on the `CreativeBrief`; missing information is stated as
absence ("no further verified business details are available"), never filled in. Visual metaphors are labelled as
creative interpretation and may not become claims.

## API

`POST /businesses/{id}/creative-directions` accepts the existing `hard_limit` plus optional `purpose`, `brand_mode`
and `creative_level`. Omitted, the business's own configured brand strategy and level apply and purpose defaults to
`hero`, so `{"hard_limit": 2.0}` behaves as before. Overrides apply to the request only and never modify the business
configuration.

## Provenance

Stored in the existing `generation_metadata.creative_spec` JSON (no migration): purpose, brand mode, level, text
policy, angle, prompt version and fingerprint, reference asset **ids** and roles, provider, model, job id, estimated
units and validation state. Never stored: presigned R2 URLs, provider result URLs beyond the existing `references`
field, API keys or credentials. Prompt text is fingerprinted, not stored.

## Validation

Metadata-only: provider completed, result exists, https result reference, expected media type and output count,
aspect ratio when dimensions are reported, and provider/model identity recorded. It **does not** detect unwanted text,
logo distortion, brand drift, composition problems or artifacts, and every result says `visual_qa: "not_performed"`
with a `not_covered` list. `GeneratedAssetValidator` is the seam for future visual QA. A failed validation is recorded
but the (already paid for) result is still returned.

## Cost semantics

`credits_used` / `estimated_generation_units` are this platform's **internal budgeting estimate** — they are not
Higgsfield credits and not USD. The first real generation reported `2.0` internally while the provider balance moved by
roughly $0.06. `estimated_generation_units` is added alongside the unchanged `credits_used` field (no migration or
breaking rename), with `cost_semantics: "internal_estimate_not_provider_credits_or_usd"`. Studio labels it
accordingly.

## Deferred follow-ups

- **TODO: real provider cost accounting.** Higgsfield's REST responses do not report cost. Options: read the account
  balance before/after (racy under concurrency), an official usage endpoint if one appears, or a calibrated per-model
  price table. Until then, `hard_limit` bounds *estimated* spend only.
- Visual QA (unwanted text, logo distortion, brand drift, composition) behind `GeneratedAssetValidator`.
- Purposes for social and decorative imagery once the product needs them.
- A website-generation step that overlays the real logo asset on generated imagery.
- Persisting the requested purpose/brand mode on the business (today they are per request).
