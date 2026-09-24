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
| `gallery` | `maxItems` 3–24, `layout` grid / featured_grid | caps the real photos used (asset *selection* stays in the generator); featured_grid uses the existing `featured` item |
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
