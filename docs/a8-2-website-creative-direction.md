# A8.2 — WebsiteCreativeDirection contract

## Why

The A8.2 diagnosis (verdict `CREATIVE_RESULT_NOT_CONSUMED`) found that a
redesign's CreativeGeneration never influences the website: the internal
provider emits a constant `{strategy, note}`, `CreativeGenerationRead`
doesn't expose it, and `generateSiteConfig(config, assets)` has no
creative input — so "Refresh" and "New direction" render identically.

A8.2.1 adds the missing seam: one normalized, provider-independent
**presentation** contract, defined and validated, not yet wired in.

```
CreativeProvider (internal | future external)
  → provider-specific output
  → WebsiteCreativeDirection (normalized, validated)
  → generateSiteConfig(business, assets, direction)   ← A8.2.3
  → SiteConfig
```

## Where it lives

| Side | Location | Role |
|---|---|---|
| TypeScript (canonical) | `packages/site-config/src/creative-direction.ts` | types, enum constants, `validateWebsiteCreativeDirection` |
| Python (mirror) | `apps/api/app/domain/creative/website_direction.py` | explicit Pydantic model (`extra="forbid"`) |
| Conformance | `packages/site-config/fixtures/creative-direction.conformance.json` | vocabulary + valid/invalid cases both suites assert |

`site-config` owns it because it describes presentation of a SiteConfig
and is already a dependency of every consumer (website-generator, Studio);
no new package and no second TypeScript copy. `website-generator`'s
`DesignFamily` is now a type alias of the contract's family vocabulary.

## What it may and may not contain

Presentation only. Every field is a closed enum, a bounded integer, or a
fixed section permutation, except `rationale` (≤280 chars, plain
single-line text, shown to the owner/operator, never rendered on the site).

It can never carry business facts (name, services, products, prices,
contact details, reviews, testimonials, ratings, projects, claims,
statistics), asset URLs or ids, font names, colour values, CSS or HTML,
or provider metadata (provider, model, credits, cost, request ids). WHAT
content exists always comes from BusinessConfig and the business's real
assets. The direction decides only how that content is arranged and styled.

| Field | Values | Intended renderer meaning (A8.2.3) |
|---|---|---|
| `version` | `"1"` | contract version |
| `strategy` | preserve / evolve / new_direction | BrandStrategy; `preserve` must use `palette.mode="brand"` |
| `family` | the 5 design.ts families | selects the family token set |
| `palette` | `brand` / `brand_derived`+derivation (tonal_shift, contrast_up, muted, vivid) / `family` | colour intent; colours computed by the generator |
| `typography.pairing` | modern_sans, system_sans, humanist_serif_display, bold_display_sans, classic_serif | one of the safe font stacks the families already ship |
| `radius` | sharp / soft / round | ≈0.25, ≈0.5, ≈1rem base radius |
| `density` | compact / comfortable / airy | section spacing scale; comfortable = today |
| `sectionOrder` | permutation of services, gallery, about | reorders real sections; hero first and cta+contact last are fixed; cannot hide or invent a section |
| `hero.layout` | split / centered | the two layouts Hero.astro already renders |
| `gallery` | `maxItems` 3–24, `layout` grid / featured_grid | caps the real photos used (asset *selection* stays in the generator). `featured_grid` enlarges the explicitly featured item, or the first one; that is today's gallery. `grid` renders uniform cells with nothing enlarged. |
| `surfaces.mode` | alternate / flat | alternating section backgrounds |
| `cta.variant` | default / emphasis | CTA.astro's existing variants |

Deliberately left out:
- `gallery.placement`: ordering belongs to `sectionOrder` alone, so the two can't contradict each other.
- `masonry` and `carousel` gallery layouts, and `full_bleed` hero: the blocks can't render them today.

## Versioning

Only `version: "1"` validates. An incompatible change becomes a new
version (its own type/model, combined in a union discriminated on
`version`), so a CreativeGeneration persisted under "1" is always
interpreted with "1" semantics; nothing reinterprets old rows silently.

## Next boundaries (not implemented)

- **A8.2.2**: InternalCreativeProvider deterministically derives a
  WebsiteCreativeDirection from the brief (strategy, industry/family,
  brand presence). No paid provider involved.
- **A8.2.3**: `generateSiteConfig(config, assets, direction?)` consumes it.
  With no direction, output stays exactly what it is today.
- **A8.2.4**: persist and expose the direction (CreativeGeneration column
  plus `CreativeGenerationRead` field; the draft keeps
  `creative_generation_id`).
- **A8.2.5**: Studio shows "What changed", and tests prove
  Refresh ≠ New direction with identical facts and assets.

Recommended order: **A8.2.2 → A8.2.4 → A8.2.3 → A8.2.5**. Studio only
receives a direction once it is persisted and exposed (A8.2.4), so the
generator (A8.2.3) can't be driven end-to-end before that. A8.2.3's
generator side can still be built and unit-tested against the
conformance fixtures in parallel.

## Persistence and exposure (A8.2.4)

- **Storage:** `creative_generations.website_direction`, a nullable JSON column added by migration
  `c4d7e2a9f1b3`. It holds the canonical v1 JSON exactly, `version` included. It is separate from
  `generation_metadata`, which is free-form provider bookkeeping.
- **Written by:** `app.creative.orchestrator.orchestrate_generation`, once.
  - The provider's `CreativeGenerationResult.website_direction` is re-validated through
    `parse_website_direction`, the single version-dispatch point.
  - A malformed direction marks the generation **FAILED** with a contract-violation error. Nothing
    malformed is stored, and credits and cost are still recorded.
  - A provider that produces no direction (every non-internal provider today) stores NULL.
- **Old rows:** NULL. They are never backfilled or reconstructed.
- **Immutability:** a `@validates` guard lets the direction be set once (None to a direction) and
  never overwritten or cleared. Regenerating creates a new CreativeGeneration.
- **Read:** `CreativeGenerationRead.website_direction: WebsiteCreativeDirection | null` is typed and
  validated through the same versioned parser, so an unknown future version fails loudly instead of
  being read as v1. Two endpoints serve it:
  - `POST /businesses/{id}/creative-generations`
  - `GET /businesses/{id}/creative-generations`

  Both keep their existing tenant scoping.
- **Traceability:** `WebsiteDraft.creative_generation_id` links a draft to its CreativeGeneration,
  which holds the direction. There is no second copy on the draft.

## Generator consumption (A8.2.3)

The signature is `generateSiteConfig(config, assets, direction?)`, and the direction is optional. Without one,
the output is byte-identical to the pre-A8.2.3 generator, guarded by
`packages/website-generator/fixtures/no-direction-golden.json`.

`packages/website-generator/src/presentation.ts` (`resolvePresentation`) is the single place a direction
becomes presentation. The block builders receive resolved values and never branch on the direction.

| Direction field | Effect |
|---|---|
| `family` | The theme family for palette purposes. The copy preset (headings, CTA wording) still follows the business's own content family, so no other industry's wording appears. |
| `palette` | `brand`: the real brand colours (the family palette if there is no brand). `family`: the family palette. `brand_derived`: a pure HSL derivation of the brand hex colours (`palette.ts`), with the foreground forced to at least 4.5:1 against the background. With no brand it uses the family palette; with a non-hex brand colour it keeps the brand colours. |
| `typography.pairing` | One of 5 local font stacks, with no remote fonts. A `preserve` direction keeps the business's own brand typography. |
| `radius` | sharp 0.25/0.375rem, soft 0.5/0.75rem, round 1/1.5rem |
| `density` | `theme.spacing` sets the `--ui-space-section-*` tokens: compact is tighter, airy is looser, and comfortable sets nothing (today's spacing). |
| `sectionOrder` | Orders the sections that exist. The hero stays first and cta+contact stay last; missing sections are skipped. |
| `hero.layout` | `content.layout` becomes `data-layout`: split (today's with-image layout) or centered (centered copy, photo below). |
| `gallery` | `maxItems` applies after the hero is excluded, keeps the existing real-before-generated order, and de-duplicates by URL. `layout` grid is uniform; featured_grid is today's look. |
| `surfaces` | alternate uses base/surface rhythm; flat sets no section backgrounds. |
| `cta.variant` | The CTA variant only; copy and destination are unchanged. |
| `rationale` | Never read by the generator and never rendered. |

Studio's RedesignFlow passes the exact `website_direction` its generation returned, after validating it with
`validateWebsiteCreativeDirection`. A missing or invalid direction is refused with a safe message and technical
details; the flow never falls back to the undirected proposal. Other callers (for example CreativeSection) remain
undirected.

The backend `SiteThemePayload` now declares `spacing` explicitly, the same A8.1.2 lesson: `extra="ignore"` would
otherwise drop it silently before the real build.
