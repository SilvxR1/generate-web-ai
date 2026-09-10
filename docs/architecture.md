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

Chatbot, CMS, Cloudinary, Storybook, Chromatic. These are real parts of the
longer-term system but are only worth the added complexity once a client
need justifies them. ("Database" and "booking system" have moved out of
this list — see above; "multi-tenancy" and "AI agents" have too — see the
Creative Orchestrator section below, which documents `apps/api`, the
backend control plane this section otherwise doesn't mention.)

## Current state

`apps/site-template` is a placeholder Astro app (no real page content or
design). `packages/ui` has seven UI primitives. `packages/blocks` has nine
business-agnostic content blocks (Hero, Services, Features, Process,
Gallery, Testimonials, FAQ, CTA, Contact) built from those primitives, each
driven by a typed `content` prop. `packages/site-config` mirrors each
block's content shape as data plus basic `SEOConfig` (title/description/
ogImage) at the site and page level. No client site has been created yet.

## Creative Orchestrator (apps/api backend layer)

`apps/api` is a separate Python/FastAPI/SQLAlchemy backend (a `uv` project,
not part of the pnpm workspace) that grew up around the frontend layer
documented above: real multi-tenancy (`Tenant`, `TenantScopedMixin` on
every tenant-owned table), a `Business` domain model, an AI Business
Analyzer, website publishing (Cloudflare Pages), and n8n-based automation.
This section documents the **Creative Orchestrator** layer added on top of
that — the architecture for producing a business's website/visual
identity through a provider-neutral pipeline, with Higgsfield as one
premium creative provider among possible future others (OpenAI, Replicate,
Flux, ...). It does not replace or duplicate the existing deterministic
website generator (`packages/website-generator`); it wraps it.

### Pipeline

```
Business (app.db.models.business)
  -> BusinessConfig (app.domain.business_config — includes CreativeConfig:
     strategy + level, see below)
  -> real assets (app.db.models.business_asset) + real reviews
     (app.db.models.business_review)
  -> CreativeBrief (app.domain.creative.brief.build_creative_brief) —
     deterministic assembly, no AI call
  -> CreativeOrchestrator.select_provider + orchestrate_generation
     (app.creative.orchestrator)
  -> CreativeProvider.generate_* (app.creative.provider)
     - InternalCreativeProvider (app.creative.internal)
     - HiggsfieldCreativeProvider (app.creative.higgsfield.provider)
  -> CreativeGeneration row persisted (app.db.models.creative_generation)
```

Applying a generation's output to the *live, published* website remains a
separate, explicit action (`POST .../website/publish`, unchanged) — the
orchestrator never touches the `Website` row itself. This is what makes
generate/regenerate/"generate a variation" all safe to call freely: none of
them can ever take down or corrupt a currently-published site.

### Business Analyzer (existing, unchanged)

`app.analysis.analyzer.BusinessAnalyzer` (an ABC) turns a natural-language
briefing into a proposed `BusinessConfig` — `AnthropicBusinessAnalyzer`
(`app.analysis.claude`) is its first, replaceable implementation. The
Creative Orchestrator reuses `BusinessConfig` as-is (it now carries a
`creative: CreativeConfig` field — strategy/level/preferred_provider) and
does not add a second analysis step; a future "extract recommended
creative direction from business facts" pass would extend this analyzer,
not bypass it.

### CreativeBrief (`app.domain.creative.brief`)

Pure domain data (no FastAPI/SQLAlchemy/provider SDK), assembled
deterministically from a business's `BusinessConfig` plus its persisted
assets/reviews — mirrors `packages/website-generator`'s own
"deterministic mapping from real facts" philosophy rather than a second,
AI-driven brief-writing step. Carries: business identity, audience,
conversion objective (derived from whether lead capture is enabled),
services, brand strategy/colors/typography, every real+generated asset
(each with its own `origin`, never blurred together), derived
`required_sections`/`animation_level`/`media_requirements`, and
`customer_insights` — a small, fixed keyword taxonomy matched against real
review text only (see `extract_customer_insights`), never an invented
claim. `differentiators` stays empty: nothing in this codebase derives them
from real data yet, and Section 6 of the design brief this was built
against explicitly lists that as future Business Analyzer work, not
something to fabricate here.

### CreativeProvider abstraction (`app.creative.provider`)

An ABC with five methods — `generate_concept`, `generate_website`,
`generate_image`, `generate_video`, `generate_visual_asset` — each
returning a normalized `CreativeGenerationResult` (status, assets,
external_reference, credits_used/estimated_cost — the latter two `None`
unless a provider actually reports them, never invented). Every
implementation declares a `capabilities: frozenset[CreativeGenerationType]`
so the orchestrator can check support before calling, and a `name`
(`CreativeProviderName`, stored on `CreativeGeneration.provider`).

- **InternalCreativeProvider** (`app.creative.internal`) — supports
  `WEBSITE_CONCEPT`/`WEBSITE` only. Does not reimplement
  `packages/website-generator`'s deterministic `generateSiteConfig()` in
  Python (that TypeScript pipeline stays the single source of truth,
  computed client-side by Studio); it records that the internal pipeline
  satisfied the request. Raises `CreativeCapabilityNotSupportedError` for
  image/video/visual-asset generation — no AI image/video generation
  exists anywhere in this codebase yet.
- **HiggsfieldCreativeProvider** (`app.creative.higgsfield`) — see the
  dedicated "Higgsfield integration status" section below.

### CreativeOrchestrator (`app.creative.orchestrator`)

`select_provider` routes by `CreativeLevel`: `BASIC`/`PROFESSIONAL` use
`InternalCreativeProvider` by design (not as a fallback); `PREMIUM`/
`CINEMATIC` require a premium provider, and if none is configured,
`select_provider` raises `NoSuitableProviderError` rather than silently
using Internal — a silent downgrade would produce a cheaper, materially
different result than what was requested. A business can also force a
specific provider via `CreativeConfig.preferred_provider`. The orchestrator
itself contains **no vendor-specific logic** — no Higgsfield/Anthropic/
Cloudflare awareness — that all lives inside each provider.

`orchestrate_generation` builds the brief, selects the provider, calls it,
and persists a `CreativeGeneration` row — `RUNNING` while in flight,
`COMPLETED` or `FAILED` once the provider call returns/raises. A
`CreativeProviderError` from the provider is caught and recorded as
`FAILED` with the error message on the row (never left unrecorded, never
re-raised as an unhandled 500) — provider failure never corrupts `Business`
state, since the orchestrator never writes to `Business`/`Website` at all.

### Business assets (`app.db.models.business_asset`)

The reusable asset library (Section 14 of the design brief this was built
against): `kind` (logo/image/video/document), `category` (a fixed
classification taxonomy — project/team/facility/product/before/after/
hero_candidate/gallery/other/low_quality — Section 3's "clean interface"
for a future automatic classifier; nothing here classifies automatically
yet, a human sets it via `PATCH .../assets/{id}`), `origin`
(uploaded/imported/generated — the provenance fact `CreativeBrief`
construction relies on to prefer real content), `storage_url` (a plain
string — no file-upload/object-storage backend exists yet, matching
Section 2's explicit "don't over-engineer storage before one exists";
registering an asset means pointing at wherever it already lives). A
`GENERATED` asset can reference the `CreativeGeneration` that produced it
(`generation_id`, `SET NULL` on delete — losing the generation record never
deletes the still-usable asset).

### Reviews (`app.db.models.business_review`)

Real, imported/provided customer reviews only — **never fabricated**.
`body` is stored and returned verbatim; nothing in this codebase rewrites
it. `source`+`source_review_id` are unique per business so a real Google
import (not implemented yet — no Google Reviews API credential/client
exists in this codebase) has a natural upsert target rather than producing
duplicates. Today, `POST .../reviews` only registers a review the caller
already asserts is real (e.g. pasted from a real listing, with its public
URL as `review_url` for provenance) — it does not call any external API.

### Generation tracking (`app.db.models.creative_generation`)

One row per `CreativeProvider` call: `provider`, `generation_type`,
`creative_level`, `status` (pending/running/completed/failed/cancelled),
`external_reference`, `credits_used`/`estimated_cost` (nullable — never
invented), `started_at`/`completed_at`, `error`. This is the traceability
history behind a future Studio summary like "Generations: 14 · Estimated
creative cost: €23.40" — `GET .../creative-generations` already returns
the full list; Studio's dashboard card doesn't aggregate it yet.

### Provider routing summary

| Creative level | Default provider | Behavior if premium unconfigured |
| --- | --- | --- |
| BASIC | Internal | n/a (Internal is always available) |
| PROFESSIONAL | Internal | n/a |
| PREMIUM | Premium (e.g. Higgsfield) | `NoSuitableProviderError` — no silent downgrade |
| CINEMATIC | Premium (e.g. Higgsfield) | `NoSuitableProviderError` — no silent downgrade |

A business can also set `CreativeConfig.preferred_provider = "higgsfield"`
to force the premium path at any level.

### Failure behavior

- **Provider not configured** (e.g. `HIGGSFIELD_API_KEY`/`HIGGSFIELD_BASE_URL`
  unset): the DI layer (`app.dependencies.get_higgsfield_provider`) raises a
  clean `503` before any provider code runs — the same "fail loud only when
  actually used" pattern every other optional integration in this codebase
  (n8n, Cloudflare, Resend) already follows.
- **Provider call fails** (including Higgsfield's current
  "not yet integrated" state — see below): caught by the orchestrator,
  recorded as a `FAILED` `CreativeGeneration` with the error message, HTTP
  response is `502` with that message. The business's own config, assets,
  reviews, and published website are all untouched.
- **Regeneration**: there is no separate "regenerate" code path —
  `POST .../creative-generations` is the one endpoint for generate,
  regenerate, and "generate a variation" alike (Section 16). Since the
  orchestrator never writes to `Website`, none of these can ever take an
  already-published site down or corrupt it; publishing a new result live
  stays its own, separate, explicit `POST .../website/publish` call.

### Studio integration

`apps/studio`'s `PreviewStep` gained a "Creative" section
(`apps/studio/src/features/business-creative/`): `CreativeConfigPanel`
(strategy/level), `AssetsPanel`, `ReviewsPanel`, `GenerationsPanel`
(history + trigger). It's revealed on demand (a "Show brand, content &
generation tools" button) rather than fetched unconditionally on mount, so
its four extra requests don't fire for a session that never opens it.

### Higgsfield integration status

**No real Higgsfield integration exists.** This repository (its code,
`.env`/`.env.example` files, and available MCP servers) was inspected for
an existing Higgsfield SDK, REST client, or MCP server config before this
layer was built — none exists, and Higgsfield provides no public API
documentation this session had access to. Rather than invent an endpoint
contract, `HiggsfieldCreativeProvider` (`app.creative.higgsfield.provider`)
implements the full boundary — configuration, DI, error handling, capability
declaration — and every `generate_*` method raises
`HiggsfieldNotIntegratedError` with a message pointing at exactly what's
missing. **It never returns a fabricated success.**

To complete the integration:

1. Obtain Higgsfield's real API documentation (auth scheme, base URL,
   endpoint paths, request/response shapes for website/image/video/visual-
   asset generation).
2. Implement the actual HTTP calls in
   `app/creative/higgsfield/provider.py`'s five `generate_*` methods, using
   `app/creative/higgsfield/client.py`'s `HiggsfieldClient.request` (already
   built, generic, unused today) as the transport.
3. Update `CreativeGenerationResult.credits_used`/`estimated_cost` mapping
   once Higgsfield's response actually reports them — do not estimate.
4. Add contract tests against a mocked `httpx.Client` (see
   `apps/api/tests/test_cloudflare_pages_publisher.py` for the existing
   pattern this codebase uses for a real external HTTP integration).

See `docs/higgsfield-integration.md` for the environment variables this
requires — no credentials are committed anywhere in this repository.

### Closing the end-to-end workflow: asset storage, safe drafts, QA

A follow-up phase closed the gap between "the orchestrator can call a
provider" and "a user can go from a real business asset to a published
website, entirely on the free InternalCreativeProvider, with no
Higgsfield account required." Four additions:

**Real asset ingestion** (`app.storage`): a `StorageProvider` ABC (same
ABC-plus-swappable-implementation shape as every other provider in this
codebase) with one implementation, `LocalStorageProvider` — writes to a
local directory (`settings.local_storage_dir`, defaulting to
`var/uploads`, the one provider setting in this codebase with a real
default, since local storage needs no account) served back over HTTP via
a `StaticFiles` mount at `/uploads` (`app.main`). `POST
.../assets/upload` (`app.routers.creative`) validates content-type
against the asset's `kind`, enforces `settings.max_upload_size_bytes`,
and generates a safe storage key (`app.storage.keys.generate_storage_key`
— never the caller's own filename) before saving. A future
`S3StorageProvider`/`R2StorageProvider` implements the same
`StorageProvider` interface without any router or service code changing.

**WebsiteDraft — a safe, pre-publish output**
(`app.db.models.website_draft.WebsiteDraft`): the missing link between a
`CreativeGeneration` and the *live* `Website` row. `app.publishing.drafts`
provides the lifecycle: `create_website_draft` persists a generated
`SiteConfig` and immediately runs the real `astro build`
(`app.publishing.build.build_site` — the same subprocess
`publish_website` itself uses) to prove it's actually publishable, never
storing the built HTML/CSS bytes (Studio's existing `SiteConfigPreview`
component already renders a structural preview directly from the JSON
`site_config`, and publishing re-runs the real build anyway).
`approve_website_draft` is the explicit human action between preview and
publish; `publish_website_draft` requires an `APPROVED` draft and reuses
`app.publishing.service.publish_website` **unchanged** — no parallel
deployment system. A `BUILD_FAILED` draft can never be approved; a
publish failure leaves the draft `APPROVED` (never silently marked
`PUBLISHED`) and the previously live site (if any) untouched — see
`app.db.models.website_draft.WebsiteDraft`'s own docstring for the full
state machine (`DRAFT -> BUILDING -> READY|BUILD_FAILED -> APPROVED ->
PUBLISHED`).

Since `InternalCreativeProvider`'s own "website" generation result
carries no content of its own (the deterministic
`packages/website-generator` pipeline stays TypeScript, computed
client-side — see that provider's docstring), Studio is what actually
bridges a completed Internal generation into a draft: after `POST
.../creative-generations` returns a completed `internal`/`website`
result, Studio computes the `SiteConfig` via the same `generateSiteConfig()`
call its own live preview already uses, then `POST`s it to
`.../website-drafts` linked to that generation's id
(`apps/studio/src/features/business-creative/CreativeSection.tsx`). A
future successful Higgsfield generation would carry its own output
instead of triggering this client-side recomputation.

**QA validation** (`app.qa.validate.validate_site_config`): a short, fixed
list of structural/content checks (hero section present, non-empty SEO
title/description, no empty testimonials section, no contact form
without a contact section) run once a draft has built successfully.
Deliberately not a fabrication check — `packages/website-generator`'s own
"no invented testimonials" rule is what actually prevents that; this only
flags a content gap. Findings are non-blocking (`validation_issues` on
the draft) and never prevent approval — only a `BUILD_FAILED` draft is
hard-blocked, since an unbuildable site can never safely go live no
matter who approves it.

**Honest provider availability** (`GET
.../businesses/{id}/creative-providers`): returns each `CreativeProvider`'s
real availability, backed directly by the same DI checks
`app.dependencies.get_higgsfield_provider` itself uses — never a
hardcoded UI placeholder. Today: `internal` always `available: true`;
`higgsfield` `available: false` with `unavailable_reason: "Higgsfield is
not configured on this server."` until `HIGGSFIELD_API_KEY`/
`HIGGSFIELD_BASE_URL` are both set (which still doesn't make generation
succeed — see the Higgsfield integration status above). Studio's
`GenerationsPanel` disables a generation type no *available* provider
actually supports, rather than leaving it selectable to fail every time.

None of this requires a Higgsfield account, credentials, or subscription
— the full `Generate -> Draft -> Build/Validate -> Preview -> Approve ->
Publish` workflow is exercised end to end on `InternalCreativeProvider`
alone (see `apps/api/tests/test_website_draft_service.py` and
`test_website_draft_api.py`).
