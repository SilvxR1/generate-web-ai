# @generate-web-ai/website-generator

`generateSiteConfig(businessConfig): SiteConfig` — a deterministic,
preset-driven mapping from `BusinessConfig` (the business-level source
of truth, `apps/api`/`@generate-web-ai/business-config-types`) onto the
*existing* website engine's `SiteConfig`
(`@generate-web-ai/site-config`). No AI, no new block types, no second
schema: every block produced is one of the ones
`@generate-web-ai/renderer`/`@generate-web-ai/blocks` already know how
to render.

```
BusinessConfig  (apps/api, Pydantic; TS types via business-config-types)
      ↓  generateSiteConfig()  +  a per-industry preset (src/presets.ts)
SiteConfig      (@generate-web-ai/site-config — unchanged)
      ↓  PageRenderer/BlockRenderer  (@generate-web-ai/renderer — unchanged)
Rendered website
```

## What it derives vs. what it never invents

Every generated field traces to a real `BusinessConfig` value, or is
generic template copy (a preset's section headings/CTA labels) that
asserts nothing about the specific business. It **never** populates
`HeroBlockContent.stat` (years-of-experience-style claims) and never
generates `testimonials`/`gallery` blocks — there's no BusinessConfig
field that could back that content honestly yet.

`About` reuses the `features` block type (no dedicated "about" block
exists in `site-config`); `Footer` is intentionally not produced at
all — it's an app-shell concern (`Header`/`Footer`/`Layout`) the
website engine has never owned, same as for hand-authored clients.
`LeadForm` is the `contact` block's existing `form` field, built from
`LeadManagementConfig.required_fields`, with no `action` set — see
`packages/blocks/src/components/Contact.astro`'s docstring for how that
turns into a neutral `lead.submitted` DOM event instead of a dead POST.

## Presets

`src/presets.ts` registers one preset per `BusinessVertical`; any
vertical without a dedicated entry falls back to a generic one rather
than throwing. `home_renovation` is the only dedicated preset so far.

## Validating

```sh
pnpm --filter @generate-web-ai/website-generator check      # tsc
pnpm --filter @generate-web-ai/website-generator validate   # real Astro
                                                              # render via
                                                              # Container API
```

`validate` renders the generated `SiteConfig` through the real
`PageRenderer` component (Astro's `experimental_AstroContainer`, the
documented way to render `.astro` components outside a full `astro
build`) using the real `reforma-casa-valencia` `BusinessConfig` fixture
from `@generate-web-ai/business-config-types`.
