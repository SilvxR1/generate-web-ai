# generate-web-ai — project brief

Paste this file into a separate Claude conversation (e.g. claude.ai) to
discuss, plan, or make decisions about this project without needing repo
access. It's a snapshot, not a live source of truth — re-check anything
time-sensitive against the actual repo before relying on it.

*Not named CLAUDE.md on purpose: a file by that name inside the repo would
be auto-loaded by Claude Code as binding project instructions the moment a
session's working directory is inside this folder, which isn't what this
document is for.*

## What this project is

`generate-web-ai` is a reusable, AI-assisted website production system for
small and medium-sized business clients (e.g. a home-renovation contractor,
a clinic, a restaurant). It's a monorepo: one shared design system, plus
one deployable Astro app per client. The bet is that these business sites
are structurally near-identical — hero, services, gallery, testimonials,
contact — and differ mainly in copy, images, and brand color/type. So the
sections live once as a shared, typed-content-driven package, and shipping
a new client is writing content/config, not writing new component code. A
fix or design improvement to a shared block benefits every client site on
its next deploy, rather than needing to be repeated per-codebase.

## Stack and why

- **pnpm workspaces + Turborepo** — standard monorepo tooling for
  independently-deployable apps sharing packages.
- **Astro** — one deployable app per client (no multi-tenancy: each client
  is its own build/deploy, not a runtime-switched tenant of one app).
- **Tailwind CSS v4**, via `@tailwindcss/vite` — deliberately *not*
  `@astrojs/tailwind`, which only supports Tailwind v3. Config is CSS-first
  (`@import "tailwindcss"`); there is intentionally no `tailwind.config.js`.
- **TypeScript strict mode everywhere**, shared base tsconfig.
- **Cloudflare** is the preferred deploy target; **GitHub** is the source
  of truth. No CI/CD specifics are locked in yet.

## Package boundaries (blast radius matters)

- `packages/ui` — accessible, low-level UI primitives (Button, Card,
  Heading, Link, Media, ...). No business/content awareness.
- `packages/blocks` — composable page sections (Hero, Services, Features,
  Process, Gallery, Testimonials, FAQ, CTA, Contact) built from
  `packages/ui`. Each block takes a typed `content` prop and knows nothing
  about any specific client.
- `packages/site-config` — the typed content/theme shapes a client's config
  must conform to (mirrors each block's `content` prop, plus theme tokens
  and SEO config).
- `packages/renderer` — `BlockRenderer`, which takes a site-config block
  list and renders the matching block for each entry, so a client app's
  page is mostly declarative config rather than JSX/Astro markup.
- `apps/site-template` — the app-shell shape (routing, layout wiring) every
  new client app is derived from.
- `apps/clients/<name>` — one real, deployable client app per client.

A change to `packages/ui`, `packages/blocks`, `packages/site-config`, or
`packages/renderer` is **shared-package blast radius**: it can affect every
current and future client site, not just the one you're looking at. A
change inside a single `apps/clients/<name>` app is scoped to that client
only. The hard rule: a client's specific need should either fit the
existing typed content shape, or motivate a deliberate, considered addition
to the shared block/primitive — never a per-client fork of shared component
code.

## Current state (as of this snapshot)

The design system is mid-way through a visual expansion pass, being proven
out on the first real client build rather than developed in the abstract:

- **New:** `Media` — a shared "framed photograph" UI primitive (aspect
  ratio, object-fit, corner radius, optional hover-zoom), consolidating CSS
  that used to be hand-rolled, slightly differently, inside several blocks.
- **Content model additions** (`packages/site-config`, threaded through the
  relevant blocks): a `featured` flag to render one item larger/emphasized
  within Services, Gallery, and Testimonials; an optional hero "stat"
  overlay (e.g. "+10 años de experiencia"); a higher-contrast CTA
  "emphasis" variant; a per-section `background: "base" | "surface"` for
  alternating section tone down a page; an optional `display` font distinct
  from body `sans`, defaulting to `sans` when omitted (existing configs are
  unaffected).
- **First real client app:** `apps/clients/reforma-casa-valencia` — a
  Valencia-based home-renovation company. Full hero, 6 services, a
  before/after project gallery, custom `Header`/`Footer`/`Layout`. This is
  the real-content stress test for the block/content-model changes above
  before they're treated as stable enough for a second client.
- `apps/site-template` remains the placeholder app-shell — no real content,
  not where the new visual work is happening.

## Conventions and guardrails already agreed

- A new client is always a new app under `apps/clients/`, never a fork of
  shared component code.
- Shared-package changes (`packages/ui`, `packages/blocks`,
  `packages/config`, `packages/site-config`, `packages/renderer`) are
  higher blast-radius than an app-local change and should be treated with
  more care.
- `packages/ui` and `packages/blocks` are consumed as TypeScript source
  directly, no build step — don't add a bundler for them unless something
  needs to consume them outside a Vite-based app.

## Explicitly deferred — do not add without a real decision

Chatbot, database, CMS, booking system, Cloudinary, Storybook, Chromatic,
multi-tenancy, AI agents. These are plausible longer-term parts of the
system (e.g. a CMS once a non-technical client needs to self-edit content;
a chatbot once a client wants one) but each adds real complexity that
isn't worth carrying until a specific client need justifies it.

## Open questions worth discussing

These aren't decided yet — good material for a planning conversation:

- When does `reforma-casa-valencia` graduate from "proving ground" to
  "done," and what does that gate look like before starting a second
  client app?
- What's the actual content-authoring workflow for a non-technical client:
  do they ever touch the typed `site-config`, or does someone on the build
  side always translate content into it? (This is upstream of whether a
  CMS is ever justified.)
- As more clients get built, at what point does a pattern repeated across
  2-3 client apps' `Header`/`Footer`/`Layout` get promoted into a shared
  package, versus staying app-local?
- No CI/CD or deployment pipeline specifics exist yet beyond "Cloudflare is
  the preferred target" — worth deciding before the first client site
  actually needs to go live.
- No visual design reference/spec exists outside the code itself — is that
  intentional (code as the design system's source of truth), or is a
  lightweight design reference worth having alongside it?
