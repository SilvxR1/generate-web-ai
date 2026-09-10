# Legal profile, legal pages, and consent architecture

P0 Phase 16-19. Covers what exists today, what it deliberately does and
doesn't claim, and where the pieces live.

## What this is not

This system does not provide legal advice, does not guarantee GDPR (or
any other law's) compliance, and no generated page has been reviewed by
a lawyer. Every generated legal page carries a visible disclaimer saying
exactly that. A business owner is responsible for reviewing and, where
needed, having a professional review the generated Privacy Policy,
Terms of Service, and Cookie Policy before relying on them.

This system also never fabricates a legal fact. A `LegalProfile` field
left blank (company registration number, tax ID, legal address, data
processors) renders as an explicit "Not provided." on the generated
page — never a guessed or invented value.

## LegalProfile (backend)

`app.domain.business_config.legal.LegalProfile` — an optional section of
`BusinessConfig`. Every field is optional:

- `legal_name` — the registered legal entity name (may differ from the
  trading name in `BusinessProfile.name`).
- `registration_number`, `tax_id`
- `address` (reuses `PostalAddress`, the same shape `ContactInfo` uses)
- `privacy_contact_email`
- `data_processors` — a human-entered list of real third parties (e.g.
  "Resend (transactional email)", "Cloudflare (hosting)"). Never
  inferred automatically.

Edited in Studio via `ProposalReview.tsx`'s "Legal profile" fieldset,
both at business creation and via "Edit business" afterward. The
TypeScript mirror (`packages/business-config-types`) is generated from
this Pydantic model exactly the way the rest of `BusinessConfig` is —
see `apps/api/scripts/export_business_config_contract.py`.

## Legal pages (generated site)

`packages/website-generator/src/legal.ts`'s `buildLegalPages()` always
adds three pages to every generated `SiteConfig`: `/privacy`, `/terms`,
`/cookies`. Unconditional — a business with an empty `LegalProfile`
still gets pages that plainly show what's missing, which is the
incompleteness signal doing its job, not this app deciding a business
doesn't need legal pages.

Each page is one `legal_text` block (`packages/site-config`'s
`LegalTextBlockContent`, rendered by `packages/blocks`' `LegalText.astro`
via `packages/renderer`'s `BlockRenderer.astro`). `disclaimer` is a
required field on that content type — a caller cannot construct a legal
page without it.

`apps/site-builder` builds every page in `SiteConfig.pages`, not just
the homepage: `index.astro` renders `path: "/"`; `[...slug].astro`
(added this phase) renders everything else via `getStaticPaths()`. Both
share `src/lib/loadSiteConfig.ts`.

## Consent architecture

`apps/site-builder/src/components/CookieConsentBanner.astro`, included
on every page via `Layout.astro`. Four fixed categories
(`app.domain.enums.ConsentCategory` on the backend, mirrored as plain
strings client-side since there's no BusinessConfig field to derive them
from):

- **Necessary** — always on, never shown as a toggle.
- **Analytics**, **Marketing**, **Preferences** — default withheld;
  granted only by an explicit visitor choice. No checkbox is ever
  preselected.

The choice persists in `localStorage` (`gwa-consent`) and is exposed via
`window.gwaConsent.isGranted(category)` — the gate any future
non-necessary script (analytics, a marketing pixel, a reviews widget)
must check before it loads anything. No stored decision reads as
"not granted" for every optional category, so the gate fails closed by
construction, not by convention.

No dark patterns: "Reject non-essential," "Save preferences," and
"Accept all" render with equal visual weight; dismissing the banner
without choosing isn't offered as acceptance — the banner stays open
until an explicit choice is made.

**Current state honestly reflected**: this codebase has no analytics,
marketing, or third-party tracking script anywhere in the generated-site
pipeline today (P0 explicitly defers that). The Cookie Policy page says
so directly rather than implying tracking that doesn't exist. The
mechanism exists and is proven to work (see
`apps/api/tests/test_site_builder_integration.py`'s consent-banner
tests, run against a real, unmocked `astro build`) so the day a
non-essential script is added, it has a real gate to check rather than
needing this architecture built retroactively.

## What's deferred (not P0)

- Google Reviews import, analytics, or any other non-essential
  integration that would actually need the consent gate above.
- Jurisdiction-specific legal page variants (e.g. a CCPA-specific
  section, an EU-specific cookie law summary) — the current pages are
  deliberately generic.
- Automatic legal-profile verification (checking a registration number
  against a real registry) — out of scope; this app records what a
  human enters, nothing more.
