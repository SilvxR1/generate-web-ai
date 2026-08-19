# Architecture — MVP scope

## Decided for the MVP

- Astro as the default frontend framework for client sites.
- TypeScript, strict mode, shared base config in `packages/config`.
- Tailwind CSS (v4) for styling.
- pnpm workspaces + Turborepo for the monorepo.
- Reusable UI primitives (`packages/ui`) and composable content blocks
  (`packages/blocks`), so a new client site is content/config, not new code.
- Feature modules (forms, chatbot, booking, ...) as a future pluggable layer
  behind provider interfaces — not built yet.
- One deployable application per client (no multi-tenancy).
- No database by default.
- No CMS for the initial MVP.
- Cloudflare as the preferred deployment target.
- GitHub as the source of truth.

## Explicitly deferred (do not add without a decision)

Chatbot, database, CMS, booking system, Cloudinary, Storybook, Chromatic,
multi-tenancy, AI agents. These are real parts of the longer-term system but
are only worth the added complexity once a client need justifies them.

## Current state

Workspace scaffold only: `apps/site-template` is a placeholder Astro app
(no real page content or design), `packages/ui` and `packages/blocks` are
empty scaffolds establishing the dependency boundary between them. No client
site has been created yet.
