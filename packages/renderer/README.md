# @generate-web-ai/renderer

Turns a typed `SiteConfig`/`PageConfig` (from `@generate-web-ai/site-config`)
into rendered `@generate-web-ai/blocks` components — the bridge between "a
site described as data" and Astro output.

```astro
---
import { PageRenderer } from "@generate-web-ai/renderer";
import { exampleSiteConfig } from "@generate-web-ai/site-config";

const page = exampleSiteConfig.pages[0];
---

<PageRenderer page={page} />
```

## Components

| Component       | Takes                | Does                                                              |
| ---------------- | --------------------- | -------------------------------------------------------------------- |
| `PageRenderer`   | `page: PageConfig`    | Renders `page.blocks` in order via `BlockRenderer`.                  |
| `BlockRenderer`  | `block: BlockConfig`  | Maps `block.type` to its `@generate-web-ai/blocks` component and renders it with `block.content`. |

`BlockRenderer` calls `assertKnownBlockType` before dispatching: a `block`
whose `type` isn't one of the seven known block types throws a descriptive
`Error` naming the offending type, rather than silently rendering nothing.
This matters for content that didn't come through the TypeScript compiler
(parsed JSON, AI-generated output).

## Validating

`pnpm --filter @generate-web-ai/renderer run validate` runs
`scripts/validate-example.ts`, a standalone Node script (no Astro, no
build step) that checks the `exampleSiteConfig` fixture from
`@generate-web-ai/site-config` covers all seven block types and passes
`assertKnownBlockType`, and that a deliberately unknown block type fails
clearly.

## Deliberately not included

Theme/brand application (CSS custom properties, `<head>` wiring), page
layout/shell (`<html>`, navigation, footer) — those are an app's concern,
not the renderer's, for this first minimal version.
