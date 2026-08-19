# @generate-web-ai/site-config

The typed schema a client site is described by, as data:

```
SiteConfig
  -> brand:    BrandConfig
  -> theme:    ThemeConfig
  -> pages:    PageConfig[]  (each with blocks: BlockConfig[])
  -> features: FeatureConfig
```

`BlockConfig` is a discriminated union on `type` (`hero`, `services`,
`features`, `testimonials`, `faq`, `cta`, `contact`), one variant per block
in `@generate-web-ai/blocks`, each with its own `content` shape. This
package has no Astro dependency — it is the layer an AI (or a human) is
meant to generate, and `@generate-web-ai/renderer` is what turns it into
Astro components.

```ts
import type { SiteConfig } from "@generate-web-ai/site-config";

const site: SiteConfig = {
  brand: { name: "Riverside Plumbing Co." },
  theme: {
    colors: { primary: "#2563eb", secondary: "#0f766e", accent: "#f59e0b", background: "#fff", foreground: "#111827" },
    fonts: { sans: "Inter, system-ui, sans-serif" },
    radius: { base: "0.5rem", lg: "0.75rem" },
  },
  features: { contactForm: true, chatbot: false, booking: false },
  pages: [
    {
      path: "/",
      blocks: [
        { type: "hero", content: { heading: "Reliable plumbing, day or night" } },
        { type: "cta", content: { heading: "Ready when you are", primaryAction: { label: "Call now", href: "tel:+15555550123" } } },
      ],
    },
  ],
};
```

`exampleSiteConfig` (exported from this package) is a complete, valid
example covering all seven block types — used by
`@generate-web-ai/renderer`'s example page and validation script.

## Type-checking

Plain TypeScript, no `.astro` files: `pnpm check` here runs `tsc --noEmit`.

## Deliberately not included

Validation beyond `assertKnownBlockType`/`isKnownBlockType` (e.g. a full
runtime schema validator), theme/brand rendering, and anything that turns
this data into HTML — that's `@generate-web-ai/renderer`'s job.
