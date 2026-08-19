# generate-web-ai

A reusable AI-assisted website production system for small and medium-sized
business clients. This is a monorepo: shared design-system packages plus one
deployable Astro app per client site, so a new client is mostly configuration
and content, not new code.

## Stack

- Package manager: pnpm, activated via corepack. Workspaces are defined in
  `pnpm-workspace.yaml`.
- Task runner: Turborepo (`turbo.json`) — `pnpm build`, `pnpm dev`, `pnpm check`
  run the corresponding task across all workspace packages.
- Framework: Astro (`apps/site-template`, and future per-client apps).
- Styling: Tailwind CSS v4, wired in via the `@tailwindcss/vite` plugin (not
  the legacy `@astrojs/tailwind` integration, which only supports Tailwind v3).
  Tailwind v4 config is CSS-first (`@import "tailwindcss"`), so there is
  intentionally no `tailwind.config.js`.
- Language: TypeScript, strict mode everywhere. The shared base config lives
  in `packages/config/tsconfig.base.json` and every package/app extends it.
- Node.js >= 24.

## Layout

- `apps/site-template` — the canonical starter app. Future client sites are
  new apps derived from this one, not copies with duplicated logic.
- `packages/ui` — reusable, accessible UI primitives (the design-system layer).
- `packages/blocks` — composable page sections (Hero, Services, Gallery, ...)
  built from `packages/ui`, used to assemble a client's pages.
- `packages/config` — shared TypeScript config, and later shared Tailwind /
  lint config as those are introduced.
- `docs` — architecture notes and decision records.

`packages/ui` and `packages/blocks` are consumed as TypeScript source
directly (no build step) — Vite/Astro compiles them on demand as workspace
dependencies. Don't add a bundler for them unless they need to be consumed
outside a Vite-based app.

## Current scope (MVP)

This repository currently contains only the workspace scaffold: shared
package boundaries and a placeholder starter app, no real UI components, no
client site, no content. The following are intentionally **not** included
yet and should not be added without an explicit decision to do so: chatbot,
database, CMS, booking system, Cloudinary, Storybook, Chromatic,
multi-tenancy, AI agents. See `docs/architecture.md` for the reasoning.

## Conventions

- A new client is a new app under `apps/`, importing `packages/ui` and
  `packages/blocks` and supplying its own content and theme tokens — never a
  fork of shared component code.
- Changes to `packages/ui`, `packages/blocks`, or `packages/config` affect
  every client site that depends on them; treat them as higher blast-radius
  than an app-local change.
