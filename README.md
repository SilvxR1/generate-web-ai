# generate-web-ai

A reusable, AI-assisted website production system for small and
medium-sized business clients. This is a monorepo: a shared design system
plus one deployable Astro app per client, so shipping a new client site is
mostly writing content and configuration, not writing new code.

## Why this exists

Small/medium business websites (a reform contractor, a clinic, a
restaurant...) are structurally the same handful of sections — hero,
services, gallery, testimonials, contact — with different words, images,
and colors. Building each one from scratch, or forking a template per
client, means every bug fix and design improvement has to be repeated
across N codebases. This repo inverts that: the sections live once, as a
shared package, and a client site is a thin app that imports them and
supplies typed content + theme tokens. Fix or improve a block once, every
client site that uses it benefits next deploy.

## Stack

- **Package manager:** pnpm, activated via corepack. Workspaces defined in
  `pnpm-workspace.yaml` (`apps/*`, `apps/clients/*`, `packages/*`).
- **Task runner:** Turborepo (`turbo.json`) — `pnpm build`, `pnpm dev`,
  `pnpm check` run the corresponding task across all workspace packages.
- **Framework:** Astro, one deployable app per client site.
- **Styling:** Tailwind CSS v4 via the `@tailwindcss/vite` plugin
  (CSS-first config, `@import "tailwindcss"` — there is intentionally no
  `tailwind.config.js`).
- **Language:** TypeScript, strict mode everywhere, shared base config in
  `packages/config/tsconfig.base.json`.
- **Node.js** >= 24.
- **Deployment target:** Cloudflare (preferred). **Source of truth:** GitHub.

## Monorepo layout

```
apps/
  site-template/           starter app — the app-shell shape every new
                            client is derived from (routing, layout wiring)
  clients/
    <client-name>/          one deployable app per client, e.g.
                            reforma-casa-valencia
packages/
  ui/                       accessible UI primitives (Button, Card, Heading,
                            Link, Media, ...) — the design-system layer
  blocks/                   composable page sections built from packages/ui
                            (Hero, Services, Features, Process, Gallery,
                            Testimonials, FAQ, CTA, Contact)
  site-config/              typed content/theme shapes each block's `content`
                            prop conforms to, plus SEO config
  renderer/                 BlockRenderer — assembles a page from a
                            site-config block list
  config/                   shared TypeScript config (tsconfig.base.json)
docs/                       architecture notes and decision records
```

`packages/ui` and `packages/blocks` are consumed as TypeScript source
directly (no build step) — Vite/Astro compiles them on demand as workspace
dependencies.

## How a client site is built

1. A new client is a new app under `apps/clients/<client-name>`, depending
   on `@generate-web-ai/ui`, `@generate-web-ai/blocks` (via the renderer),
   `@generate-web-ai/site-config`, and `@generate-web-ai/renderer` as
   workspace packages.
2. The client app supplies:
   - **Content** — a typed `site-config` object listing which blocks appear
     on each page and their content (copy, images, actions).
   - **Theme tokens** — colors, fonts, radii — the client's brand applied
     on top of shared components.
   - **Assets** — its own images, referenced by the content config.
   - A handful of app-shell pieces the design system doesn't own: `Header`,
     `Footer`, `Layout`, page routing.
3. `BlockRenderer` (`packages/renderer`) reads the site-config block list
   and renders the matching block from `packages/blocks` for each entry.
4. Nothing in `packages/ui` or `packages/blocks` is forked or edited
   per-client — client-specific needs either fit the existing typed content
   shape, or motivate a deliberate addition to the shared block/primitive
   (which then benefits every other client).

## Current status

- `packages/ui` — 8 primitives, including `Media` (a shared framed-image
  treatment: object-fit/aspect-ratio/radius/hover-zoom, replacing
  near-duplicate CSS that used to live in each block).
- `packages/blocks` — 9 content-agnostic sections (Hero, Services,
  Features, Process, Gallery, Testimonials, FAQ, CTA, Contact), each driven
  by a typed `content` prop. Recently extended with a richer visual
  vocabulary: a `featured` flag for standout items (services, gallery,
  testimonials), an optional hero stat overlay (e.g. "+10 años"), a
  higher-contrast CTA "emphasis" variant, per-section alternating
  background tone, and an optional display typeface for headings.
- `packages/site-config` / `packages/renderer` — typed content shapes and
  the block-list-to-page renderer, kept in step with the block changes
  above.
- `apps/site-template` — the placeholder starter app (app-shell only, no
  real content).
- `apps/clients/reforma-casa-valencia` — the **first real client build**,
  in progress: a Valencia-based home-renovation company, exercising the
  full block set with real copy, a before/after project gallery, and six
  services. This is the proving ground for the design-system changes above
  before they're considered stable for the next client.

See `docs/architecture.md` for the architecture decisions behind these
choices, and what's explicitly deferred.

## Development

```bash
pnpm install        # install all workspace dependencies
pnpm dev             # run dev servers across workspace packages/apps
pnpm build           # build all workspace packages/apps
pnpm check           # typecheck/lint across all workspace packages/apps
```

To work on a single app, use Turborepo filtering, e.g.
`pnpm turbo run dev --filter=@generate-web-ai/reforma-casa-valencia`.

## Explicitly out of scope for now

Chatbot, database, CMS, booking system, Cloudinary, Storybook, Chromatic,
multi-tenancy, AI agents. These are plausible future parts of the system
but are intentionally not built until a real client need justifies the
added complexity — see `docs/architecture.md`.
