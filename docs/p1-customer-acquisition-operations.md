# P1 — Customer Acquisition & Operations

Extends P0's production-ready platform into a system that helps a
customer business actually receive, track, and operate on real customer
acquisition. This document covers what P1 added; see `architecture.md`
for the P0 baseline these features build on.

## WhatsApp (P1.1)

`BusinessConfig.whatsapp` (`app.domain.business_config.whatsapp.WhatsAppConfig`)
is a business's opt-in WhatsApp contact channel — a high-conversion CTA
(a `wa.me` deep link, optionally with prefilled text), not WhatsApp
Business API automation. `enabled=True` requires a real `phone_number`;
`BusinessConfig` refuses to validate otherwise (no fabricated numbers).

Two independently-configurable placements, mirrored 1:1 by
`show_floating_button`/`show_contact_cta`:

- **Floating button** — site-wide, rendered by
  `apps/site-builder/src/components/WhatsAppFloatingButton.astro` via
  `Layout.astro`.
- **Contact-section CTA** — a prominent button inside the Contact block
  (`packages/blocks/src/components/Contact.astro`'s `whatsappCta` prop),
  built by `packages/website-generator/src/blocks.ts`'s
  `buildContactWhatsAppCta`.

Both are plain `<a href="https://wa.me/...">` links — no script executes
on click beyond the generic analytics beacon (below), so there is no
script-injection surface from user-controlled content; the phone number
is digit-filtered and the message is `encodeURIComponent`-escaped.

## Email / Resend (P1.2)

Reused/extended P0's notification boundary
(`app.notifications.sender.NotificationSender`,
`app.notifications.resend.ResendNotificationSender`,
`app.notifications.smtp.SmtpNotificationSender`). New in P1: explicit
delivery-state tracking via `app.domain.enums.NotificationDeliveryStatus`
(`PENDING`/`SENT`/`FAILED`/`NOT_CONFIGURED`):

- `InternalNotification.status` — the business's own team notification.
- `Lead.acknowledgement_status` — the visitor's confirmation email.

Both are separate from `Lead.status` (the follow-up pipeline stage) by
design. A Lead is always persisted before any delivery attempt, and a
delivery failure never removes or blocks it — see
`app.routers.public.create_public_lead` and
`app.notifications.service`.

## Lead Operations (P1.3)

`GET /businesses/{id}/leads` gained optional `search`/`status`/`source`
query params (`app.repositories.lead.LeadRepository.list_for_business`).
`LeadNote` (`app.db.models.lead_note`) is a flat, tenant-scoped internal
note list per lead — not an activity timeline — exposed via
`GET`/`POST /businesses/{id}/leads/{id}/notes`. Studio's `LeadsList`
renders search/filter controls, direct `mailto:`/`tel:`/`wa.me` contact
actions, the acknowledgement-email state, and an expandable notes panel.

## Website Health (P1.4/P1.5)

`app.monitoring` — HTTP, DNS, TLS-certificate, and a safe contact-form
presence check (`app.monitoring.checks`), orchestrated per business
(`app.monitoring.service.run_website_health_check`) into one
`WebsiteHealthCheck` row per business (`app.db.models.website_health`) —
a latest-snapshot table, not a growing history. `HealthStatus`
(`HEALTHY`/`DEGRADED`/`DOWN`/`UNKNOWN`) is a single vocabulary for every
sub-check and the overall rollup; UNKNOWN is never reported as healthy.

**SSRF protection**: every check reuses `app.security.ssrf.validate_outbound_url`
(the same guard n8n's `http.request` action already uses) — the URL/host
checked is always sourced from the business's own persisted
`Website.deploy_url` or an ACTIVE `CustomDomain.domain`, never a
caller-supplied value. Loopback, private ranges, link-local, and the
cloud metadata address (`169.254.169.254`) are all rejected before any
network call.

**Form health** never submits anything or creates a fake Lead — it
inspects the already-fetched page HTML for a real `<form` element.

**Scheduling boundary**: `POST /businesses/{id}/website-health/check`
(rate-limited) is a plain, schedulable API — any future cron/n8n/worker
can call it. The check logic itself has no dependency on who triggers it.

Studio's `WebsiteHealthPanel` renders the Overall/HTTP/Latency/DNS/
SSL/Deployment/Contact-form/Last-checked grid plus a "Check now" button.

## Google Reviews (P1.6)

`app.reviews.provider.ReviewProvider` — `ManualReviewProvider` (always
available; manual import already existed in P0 as a plain CRUD endpoint)
and `GoogleReviewProvider` (honestly reports unavailable until real
`GOOGLE_REVIEWS_API_KEY`/`GOOGLE_REVIEWS_PLACE_ID` are configured — no
scraping, no undocumented endpoint, no invented API response).
`GET /businesses/{id}/review-providers` exposes both, real-config-backed.

`BusinessReview.is_visible` (default `True`) lets a business show/hide a
review on its website without deleting it or its provenance
(`source`/`source_review_id`/`raw_payload` never change) — via
`PATCH /businesses/{id}/reviews/{id}/visibility`. Studio's `ReviewsPanel`
exposes a Show/Hide toggle per review.

**Deferred**: an actual Google Places/Business Profile API integration,
and LLM-derived review-insight summaries — both explicitly out of scope
per the brief's "do not add a paid dependency" / "leave behind a future
boundary" guidance. Website generation does not yet read
`BusinessReview` into a Testimonials block — see "Known gaps" below.

## Analytics (P1.7/P1.8)

`AnalyticsEvent` (`app.db.models.analytics_event`) — `page_view`,
`cta_click`, `whatsapp_click`, `lead_form_started`, `lead_submitted`,
`phone_click`, `email_click`. Deliberately shallow: no session id, no
device fingerprint, no IP; `metadata` is a small, key-allowlisted,
PII-scanned JSON blob (`app.schemas.analytics.AnalyticsEventCreateRequest`
rejects anything containing an email-shaped or long-digit-run value).

`AnalyticsProvider` (`app.analytics_events.provider`) is the swappable
ingestion boundary; `InternalAnalyticsProvider` (writes straight to this
codebase's own database) is the only implementation — no external
analytics SaaS dependency.

**Consent**: `apps/site-builder/src/components/Analytics.astro` never
sends an event before `window.gwaConsent.isGranted("analytics")` — an
earlier event is queued in memory and flushed only on a later
`gwa-consent-change` grant. There is no fail-open path.
`lead_submitted` is a funnel signal only; the authoritative, always-known
lead count is the `Lead` table itself (a functional record of a
requested service, independent of analytics consent).

`GET /businesses/{id}/metrics?window=7d|30d|90d`
(`app.analytics_events.metrics.compute_business_metrics`) aggregates
website visits / WhatsApp / phone / email clicks (from `AnalyticsEvent`,
`None` — "No data yet" — until at least one has ever been recorded for
that business) and form leads / conversion rate (from `Lead`, always a
known count). Studio's `BusinessMetricsPanel` renders this with a window
selector.

## n8n relationship (P1.10)

Unchanged from P0's guarantee: `POST /public/businesses/{id}/leads` and
`POST /public/businesses/{id}/events` work with zero n8n involvement.
When automation is active, the generated contact form posts directly to
n8n's own webhook instead (`app.automation.n8n`); n8n calls back into
`/internal/leads`/`/internal/notifications` for delivery. No new
"public lead → best-effort n8n notify" hook was added this phase — see
"Known gaps."

## Provider availability (P1.12)

Three availability endpoints, all following the same honest,
real-settings-backed shape (`{provider, available, unavailable_reason}`):
`GET /businesses/{id}/creative-providers` (P0), `GET .../review-providers`
(P1.6), and `GET .../operational-providers` (P1.12 — email + n8n). None
ever report a provider available just because credentials exist in code;
all read `app.config.settings` at call time.

## PUBLIC_API_BASE_URL (site-builder)

`apps/site-builder`'s `Analytics.astro` reads `import.meta.env.PUBLIC_API_BASE_URL`
at build time — Astro's standard "exposed to client JS" env prefix. Set
it to this backend's real public URL in whatever environment runs
`astro build` for a client site; leave it unset in local/preview builds
and the analytics beacon becomes a safe no-op (it never throws).

`SiteConfig.businessId` (`app.schemas.site_config.SiteConfigPayload.businessId`,
camelCase to match the JSON contract) is injected server-side by
`app.publishing.drafts.create_website_draft` / `app.publishing.service.publish_website`
right before every real build — never trusted from a request payload —
so a generated site can identify itself to the analytics endpoint.

## Known gaps / recommended next steps

- **Contact form still doesn't POST to the public lead endpoint.** A
  generated site's Contact block (`packages/blocks/Contact.astro`)
  dispatches a local `lead.submitted` DOM event when no automation
  `action` is configured — nothing in the generated site currently POSTs
  that data to `/public/businesses/{id}/leads`. Wiring this up correctly
  needs: a honeypot field + submission-timing field in the generated
  form (required by `app.leads.spam.is_spam`), and a `subject`-labeled
  field (the generated form's `service` field doesn't map directly).
  This was investigated but deliberately not implemented this phase to
  avoid shipping a half-correct, silently-lossy integration — see the
  final P1 report for the full reasoning.
- **Reviews are not yet fed into website generation** as a Testimonials
  block — `is_visible` is the flag a future integration should filter
  on.
- **Review insights** (LLM-derived themes) are explicitly deferred.
- **A real Google Reviews API integration** is explicitly deferred —
  `GoogleReviewProvider` is an honest availability boundary only.
