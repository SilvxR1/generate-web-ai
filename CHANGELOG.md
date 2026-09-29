# Changelog

This file is the **canonical product release record** for generate-web-ai.

The repository has no other authoritative product version: every workspace
`package.json` and `apps/api/pyproject.toml` carry the placeholder `0.0.1`
(private, unpublished packages), and `apps/api/app/config.py` holds the API's
own runtime version string reported by `/health`. Those are deliberately not
bumped to mark a product release — see
[Versioning](docs/v0.2-generative-website-architecture.md#versioning) in the
v0.2 architecture document for what executable versioning would require.

## [0.2.0] — Generative Website Architecture

**Status: In development.** This section marks the *start* of the v0.2.0
line. Nothing below is implemented yet; production still runs the v0.1.x
architecture unchanged.

Full plan: [`docs/v0.2-generative-website-architecture.md`](docs/v0.2-generative-website-architecture.md).

### Why

Production-style testing (the Nexo Reformas onboarding test) confirmed that
the v0.1.x block-based generator produces functional, operationally safe
websites, but their visual composition remains recognizably
template/block-constrained: even when a creative direction changes palette,
typography, density, section order, hero variant, gallery layout or surfaces,
the result still reads as a composition of predefined blocks.

v0.2.0 replaces the **creative generation and website-source architecture** so
website design can be substantially more unique, while preserving every
platform guarantee validated during v0.1.x. It is not a platform rewrite.

### Architectural direction

From:

```
Business → CreativeDirection → predefined blocks → SiteConfig → Astro → WebsiteArtifact
```

Toward:

```
Business Truth → Creative Director → Creative Blueprint → generative Website Builder
→ free-form website source → Platform Adapter / SDK → PlatformContract + TruthContract
→ WebsiteArtifact
```

The downstream lifecycle stays as it is:

```
WebsiteArtifact → private storage → WebsiteDraft → real preview → explicit approval
→ publish exact bytes → WebsiteVersion
```

### Architectural boundary

> **Everything before WebsiteArtifact may evolve.
> Everything after WebsiteArtifact should remain stable.**

The migration replaces *business/creative input → website source generation*
and preserves *WebsiteArtifact → Preview → Approve → Publish → Operate*.

### Safety principle

> **The AI controls how the website looks.
> Generate Web AI controls what the website may claim, what platform
> capabilities it must contain, and how it is validated, previewed, published
> and operated.**

### Preserve

These capabilities must survive the migration (tracked per capability in the
Feature Preservation Matrix):

- authentication / authorization and tenant isolation
- business lifecycle and real business information
- persistent assets and asset provenance (real logo, real customer photos)
- no fabricated reviews, testimonials, projects or claims
- leads, email delivery, n8n automation, WhatsApp CTAs
- analytics, consent, SEO, legal pages, reviews architecture
- custom domains, health/readiness, monitoring, backup/recovery
- WebsiteDraft lifecycle, Build Once / Promote, immutable WebsiteArtifact,
  SHA-256 integrity validation
- real preview, Cloudflare Access preview protection, preview side-effect
  suppression
- explicit approval, exact-byte publishing, WebsiteVersion history, rollback
- failure safety, provider and cost tracking

### Creative architecture

Predefined blocks/templates are **no longer intended to be the primary creative
architecture**. The current generator (`packages/website-generator`,
`packages/blocks`, `SiteConfig`) remains available as the
**LEGACY / BASIC / FALLBACK** builder during the migration and is not deleted.
The future primary path allows substantially freer website composition.

### Provider independence

No provider — Higgsfield included — may become a hard architectural
dependency. Creative direction and website building sit behind provider
abstractions:

- `CreativeDirectorProvider`: Internal, Higgsfield, future providers
- `WebsiteBuilderProvider`: LegacyBlockBuilder, GenerativeWebsiteBuilder,
  future builders

### Roadmap

R0 Architecture freeze + Feature Preservation Matrix · R1 Business Truth /
Asset Manifest · R2 Creative Blueprint v2 · R3 WebsiteBuilderProvider ·
R4 Platform SDK · R5 PlatformContract v2 + TruthContract · R6 isolated
generation workspace · R7 WebsiteSource → validated WebsiteArtifact ·
R8 Studio generative workflow · R9 shadow benchmark vs legacy · R10 controlled
real-business pilot.

### Progress (v0.2.0 in development)

- **S0: Secure Generative Build** (#59). Generative builds no longer
  inherit the API environment. Installs are deterministic
  (`npm ci --ignore-scripts`, vetted lockfile), and the experimental
  generative path is off by default and refused server-side.
- **S1: Artifact-backed Exact Rollback.** Rollback restores a version's
  exact stored, SHA-verified WebsiteArtifact, with no rebuild, generator or
  provider. Every failure fails closed, and a rollback is recorded as a new
  version with `rolled_back_from_version_id`. `WebsiteVersion.artifact_key`
  gives every new version durable artifact provenance. Pre-artifact
  historical versions keep a legacy SiteConfig rebuild, which is not
  exact-byte.

- **R1: Business Truth.** `app.domain.business_truth` is a deterministic,
  provider-independent representation of what the platform knows:
  identity, description, services, contact, location, hours, legal, real
  vs generated assets, the real logo or none, visible reviews with
  provenance, and no unsupported claims. The experimental generative
  engine's only factual input is now a `BUSINESS TRUTH` block with explicit
  no-fabrication rules, and its legal pages reach parity with the legacy
  ones (legal name, registered address and more; missing items shown as
  "not provided"). Generated presentation is never promoted into Business
  Truth. The Truth Contract (output validation) is not implemented yet.

- **R2: Generative Platform Feature Parity.** "No platform capability may
  require a predefined visual block; platform contracts constrain behavior
  and truth, not composition." Consent is now platform-owned for
  generative sites: an injected banner shares the legacy hooks, and the SDK
  gains `gwaConsent.set/open`. PlatformContract 1.1.0 adds
  renderer-independent checks:
  - consent controls and override protection;
  - legal-page reachability and internal links;
  - no external scripts;
  - runtime-config shape;
  - authoritative WhatsApp destinations.

  The prompt now states behavior, not layout. A deterministic free-form
  fixture is built for real, passes the contract, becomes a
  WebsiteArtifact, and is tested in a real browser: consent-gated
  analytics, lead attribution, and preview suppression of its exact
  requests. Legacy builds pass the same contract. Nothing is removed.

- **R3: Truth Contract** (`app.qa.truth_contract`, 1.0.0). "Generated
  websites may transform presentation, but may not expand business truth."
  It is a deterministic, zero-provider validation of every rendered page
  against BusinessTruth, run after PlatformContract and before storage.
  - It **blocks** generative drafts: contact destinations, legal
    identifiers, fabricated reviews/ratings/counts, numeric claims, 24/7,
    rankings, certifications/awards, street addresses and asset identity.
  - Ambiguous marketing is advisory. BASIC drafts record findings as
    advisory only.
  - Nothing is re-validated on rollback, and there's no AI repair loop.
  - Arbitrary semantic claims and JS-rendered content are documented as
    not yet enforceable.

- **R4: Isolated Generation Worker — preparatory, infrastructure decision
  pending.** "Untrusted generated code must never execute inside the
  trusted API process or with access to platform secrets."
  - `astro build` of generated code now runs only in a bubblewrap build
    zone: no env, no network, workspace-only filesystem, own PID namespace,
    resource limits. It fails closed where the host can't enforce it.
  - Build output is a bounded, link-free candidate that the trusted
    contracts judge.
  - Durable, idempotent `GenerationJob` state machine (no automatic
    retries).
  - Proven by real malicious fixtures on local and CI hosts. Railway
    production feasibility is **unproven**, so the S0 gate stays OFF.

- **R4.1: Production sandbox host decision.** A manual probe proved that
  the Railway container runtime denies user, network and PID namespaces,
  so Railway stays the control plane and untrusted execution moves to an
  external host.
  - Visual QA now runs generated JavaScript in Chromium inside the build
    zone, with no network; the business's own assets are served offline.
  - New provider-independent, dormant integration layer:
    - job-scoped pull protocol;
    - claim-only worker credential and per-job HMAC result token;
    - worker executor, entrypoint and self-test;
    - trusted candidate intake (SHA-256, archive shape, re-derived CSP,
      PlatformContract, TruthContract, READY).
  - Adds the host acceptance contract and `scripts/r4_host_acceptance.sh`.
  - Recommended host: a single hardened KVM VM (not provisioned).
  - The S0 gate stays OFF until a real host passes acceptance.

### Known debts carried into v0.2

Kept visible, not resolved by this release transition:

- `A8_PREVIEW_CLEANUP_DEBT` — previews of abandoned drafts accumulate (behind
  Cloudflare Access).
- `A8_STORAGE_PRIVACY_DEBT` — business assets are served from public R2
  (`r2.dev`) URLs; scope to be reviewed.
- `A8_TEST_DISCOVERY_DEBT` — open test-discovery follow-up.
- `A8_WWW_DOMAIN_DIAGNOSTIC` — `www.` of an attached custom domain does not
  resolve (seen on the Cositas pilot).
- Operator/user access is provisioned by an untracked local script
  (`apps/api/scripts/bootstrap_operator.py`), not a reproducible,
  documented flow.
- `GENERATIVE_BUILD_NETWORK_ISOLATION_DEBT` — v0.2 S0 removed inherited
  secrets from generative builds, made installs deterministic
  (`npm ci --ignore-scripts`, vetted lockfile) and disabled the generative
  path by default, but builds still have network, filesystem and process
  access as the API user. R4 closes this for hosts that can run its
  bubblewrap build zone (verified locally and in CI). The Railway runtime
  cannot host it (namespaces denied, R4.1 probe). **Still open for
  production** until an external execution host passes the R4.1 acceptance
  procedure. Visual QA is now inside the zone (R4.1).
- Rollback of **historical** versions published before artifacts were
  recorded still rebuilds their SiteConfig (legacy compatibility, not
  exact-byte). Every version since S1 is artifact-backed and restored
  exactly.

## [0.1.x] — Validated platform foundation / legacy block-generation architecture

**Status: In production.** v0.1.x built and validated the operational platform
around website generation. It is the foundation v0.2 keeps — its limitation is
a visual-differentiation ceiling in the block-based creative engine, not the
platform.

Validated in v0.1.x (see the git history for each milestone's PR):

- **Business lifecycle** — briefing → AI analysis → reviewed BusinessConfig →
  business; edit, delete, status visibility.
- **Authentication & authorization (A2)** — session auth, CSRF, explicit
  TenantAccess; tenant isolation on every business-scoped endpoint.
- **Security remediation (A3.1)** — SVG upload, SSRF redirect handling,
  paid-provider rate limits.
- **Persistent business assets** — upload, batch, replace, verify, provenance.
- **Creative generation (P2.x)** — provider abstraction, internal and
  Higgsfield providers, brand intelligence, visual scene planning, Visual QA,
  factual safety, provider/cost tracking; an experimental generative
  frontend-engine track.
- **Deterministic website generation (A8.1–A8.3)** — WebsiteCreativeDirection
  contract, internal director, content distribution, header/navigation.
- **Lead capture, email, n8n, WhatsApp, analytics (P0 / A4 / A8.3.4-P0)** —
  server-side lead persistence with n8n dispatch after the fact; CSP allowing
  the public API.
- **Consent, SEO and legal integration**; **PlatformContract** gate on every
  build.
- **Publishing** — Cloudflare Pages, WebsiteVersion history, rollback, custom
  domains, website health and production readiness.
- **Monitoring & alerting (A6.1)**, backups / point-in-time recovery drill.
- **Build Once / Promote (A8.3.4.1)** — one build per WebsiteDraft, immutable
  WebsiteArtifact in private storage, SHA-256 integrity verification, publish
  promotes the exact bytes.
- **Real draft preview (A8.3.4.2)** — the stored artifact deployed to a
  dedicated, Cloudflare Access-protected preview project; server-side preview
  lead/event suppression; Studio "Open real preview".
- **Test network isolation** — frontend tests fail closed on any unmocked
  network request.
- **First website artifact promotion (A8.4)** — the first website goes live
  through the same lifecycle as a redesign:

  ```
  Generate → WebsiteDraft → Build Once → Real Preview → Approve → Publish exact bytes
  ```

  This downstream lifecycle is what v0.2 must preserve.
