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
- No database by default — the exception is a real, per-client need: see the
  booking-system decision below.
- No CMS for the initial MVP.
- Cloudflare as the preferred deployment target.
- GitHub as the source of truth.

### Booking system (decided, per client — sacri-barber only so far)

`sacri-barber` (a test client) has a real appointment-booking feature backed
by Cloudflare D1: one SQLite database per client app that needs it, deployed
as a Cloudflare Worker (adapter: `@astrojs/cloudflare`) alongside the
otherwise-static site — see `apps/clients/sacri-barber/src/lib/booking` and
`src/pages/api/booking/*`. This does **not** apply to every client
automatically; a new client only gets D1 + the adapter if it actually needs
booking, the same way `reforma-casa-valencia` has neither and stays plain
static output. The implementation is deliberately app-local for now, not a
shared `packages/booking`, until a second real client's booking needs
validate that the shape generalizes.

## Explicitly deferred (do not add without a decision)

Chatbot, CMS, Cloudinary, Storybook, Chromatic, multi-tenancy, AI agents.
These are real parts of the longer-term system but are only worth the added
complexity once a client need justifies them. ("Database" and "booking
system" have moved out of this list — see above.)

## Current state

`apps/site-template` is a placeholder Astro app (no real page content or
design). `packages/ui` has seven UI primitives. `packages/blocks` has nine
business-agnostic content blocks (Hero, Services, Features, Process,
Gallery, Testimonials, FAQ, CTA, Contact) built from those primitives, each
driven by a typed `content` prop. `packages/site-config` mirrors each
block's content shape as data plus basic `SEOConfig` (title/description/
ogImage) at the site and page level. No client site has been created yet.
