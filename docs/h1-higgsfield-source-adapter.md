# H1 — GWA Platform Adapter proof of concept (Higgsfield export → WebsiteArtifact)

Status: **proof of concept, local only.** Nothing is published, uploaded or
enabled; the generative feature gate is unchanged.

## Principle

Higgsfield is the **creative** authority; GWA is the **platform** authority.
The adapter never re-expresses an exported site as SiteConfig/blocks/Astro.
It keeps the exported source and changes only platform behavior and
business facts, through fixed, traceable edits.

## Pipeline (`app/creative/source_adapter`)

| Step | Module | Reusable? |
|---|---|---|
| Immutable, hash-identified snapshot of the export ZIP (safe extraction, per-file SHA-256, read-only) | `snapshot.py` | yes |
| Remove code that needs unavailable private workspace packages — only if unreachable from the public site; stop if the site needs them | `cleanup.py` | yes (TS/React exports) |
| Traceable primitives: exact-once patches, typed content bindings, new platform files | `records.py`, `mapping.py` | yes |
| Source-specific mapping (lead transport, legal routes, fonts, prerender, bindings) | `mappings/nexo_reformas.py` | **no** — one per export |
| Trusted `bun install --ignore-scripts` (validated inputs, scrubbed env) + the export's own build in the **R4 BubblewrapRunner** (no network) | `static_build.py` | yes (Bun/Vite family) |
| Static artifact: platform runtime + consent injected, platform-owned `robots.txt`/`sitemap.xml`/`_headers` | `static_artifact.py` | yes |
| Contracts, `artifact_sha256`, `pack_artifact` | `pipeline.py` | yes |
| Local preview that applies the artifact's own `_headers` (real CSP) | `preview.py` | yes |

Shared-code changes (each default-neutral, tested in `tests/test_h1_platform_extensions.py`):

- `security_headers.CspExtensions` — trusted per-source-family CSP additions
  (`media-src 'self' blob:`, exact https style/font origins). Default output
  byte-identical. `drafts.judge_generative_candidate(csp_extensions=…)` passes
  it through (default `None` = unchanged).
- `frontend_engine.build.inline_script_hashes` — hashes what the browser
  hashes (U+0000 → U+FFFD, CRLF → LF). TanStack's dehydrated state contains
  U+0000; the raw-byte hash made the real CSP block hydration. Unchanged for
  every Astro build.
- `frontend_engine.build.inject_platform_runtime` — the existing config +
  consent injection, exposed for reuse (same bytes).
- `frontend_engine.browser_qa` navigates to `/` (what hosts serve) instead of
  `/index.html`, which a client router treats as a different route.
- `legal_pages.legal_page_content` — the legal wording, rendered by both the
  Astro pages (unchanged) and exported sources.
- `truth_contract`: an email that appears in shipped JS **only** as a form
  `placeholder` value is not a published contact (mirrors the HTML rule).
  Any other occurrence still blocks.

## Result on the real export (nexo-reformas-web.zip)

- ZIP SHA-256 `f3fbc3e76caf53f8df4ae6d6819be7afcd24190af396172cd0ca68de31e0ea8f`
  (225 files, 31.1 MB, React 19 + TanStack Start 1.168 + Vite 8 + Tailwind 4, bun).
- Cleanup: 4 unavailable `@higgsfield/*` workspace packages, 1 unused route
  (`/app`), 42 unreachable scaffold modules, 9 CSS lines — identical to the
  portability spike's manual cleanup. No Nexo design file removed.
- Mapping: 15 patches, 14 BusinessTruth bindings, 8 new platform files,
  3 backend files removed, 2 OFL font packages added (72 recorded changes
  in total, including the cleanup).
- Build: TanStack Start's documented `prerender` → static `index.html`,
  `privacy/`, `terms/`, `cookies/`. Install ~2 s (trusted), build ~5 s in the
  R4 sandbox (bubblewrap + cgroup scope, all limits enforced, no network).
- Artifact: 124 files, 31.7 MB. PlatformContract 1.1.0 and TruthContract
  1.0.0: **0 findings**. Accepted READY by the real
  `judge_generative_candidate`, with the stored identity equal to the built one.
- Local preview QA (`scripts/h1_preview_qa.py`, real CSP, local GWA-compatible
  API from the real schemas/CORS/spam check): 41/42 checks pass; the one
  failure is a pre-existing Higgsfield 12 px mobile overflow (identical on the
  original). Screenshots at the spike's exact offsets: 0.00% pixels changed at
  19/20 positions, 0.63% at one (sub-pixel glyph rendering).

## Visible additions

1. Footer bottom bar: legal links + "Preferencias de cookies" (site's mono style).
2. `/privacy`, `/terms`, `/cookies` pages built from the site's own classes.
3. Platform consent banner, themed via `--gwa-consent-*` with the site's tokens.
4. Success state reads "Solicitud recibida" (the Lead API never returns an id; none is invented).
5. No `og:image` (the Higgsfield-CDN image was removed; GWA must set an owned one).

## Known limitations / required before a real customer

- ~~Intake must pass the source-family CSP~~ and ~~Visual QA must apply
  `_headers`~~ — **closed by H1.1** (see below).
- **Build is not bit-reproducible**: TanStack writes `updatedAt` timestamps
  into the dehydrated state (5 files differ between builds). Packaging is
  deterministic and Build Once stores the built bytes, so identity holds.
- **Lead schema gaps**: no structured fields for surface area / service; they
  travel as `subject` + a labelled line in `message`.
- **Legal and consent copy are English** (platform text) on a Spanish site.
- **Cabinet Grotesk** stays on Fontshare's CSS API: its licence text for
  self-hosting could not be read; Inter Tight / IBM Plex Mono are self-hosted
  (OFL-1.1). Remote fonts expose visitor IPs to the font CDN (privacy review).
- **TruthContract logo detection gap**: images are treated as logos only if
  `alt`/`class`/`id` contain "logo". Nexo's generated brand mark
  (`.nx-nav__mark`) is not detected; no exemption was added.
- **Only name, city and country are bound.** Services, process and chapter
  copy are Higgsfield literals; Studio edits to them need a source change.
- **R4 for this family** needs bun (bound read-only), ~1–1.5 GB RAM for `tsc`,
  and a per-family prepared-dependency set (455 MB `node_modules`).
- Supercomputer generation is still manual (separate automation gap).

## H1.1 — source-family CSP propagation and artifact-faithful Visual QA

**Invariant:** the `_headers` Visual QA serves the site with are byte-for-byte
the `_headers` that are stored, previewed and published.

### Policy (`app/publishing/csp_policy.py`)

| Source family | Additions to the GWA baseline |
|---|---|
| `gwa-astro` (default; deterministic + generative Astro) | none |
| `higgsfield-tanstack-static` (H1 Higgsfield exports) | `media-src 'self' blob:`; `style-src` + `https://api.fontshare.com`; `font-src` + `https://cdn.fontshare.com` |

- Hard platform allowlist (`PERMITTED_*`): a family policy outside it fails at
  import. `script-src`, `connect-src`, `img-src` and every non-CSP header are
  never changed by a family.
- `CspExtensions` accepts only exact `https://host` origins, so
  `'unsafe-inline'`, `'unsafe-eval'`, `*`, `https://*.x`, `https:`, `blob:`,
  `data:` and paths cannot be expressed as an origin.
- Unknown family, or a source requesting more than its family policy
  (`validate_requested`): `UnsupportedCspRequirementError` — fail closed.

### Propagation

1. `generation_jobs.source_family` (migration `d2b7e4a9c1f3`, NOT NULL, default
   `gwa-astro`): chosen by trusted code at enqueue; `submit_job` validates it;
   an idempotency key cannot switch family.
2. `ExecutionRequest.source_family` → the execution host builds with
   `policy_for(family)`. The host builds GWA Astro sources only; any other
   family is rejected explicitly (`CANDIDATE_REJECTED`), never built with the
   wrong policy. The host records `headers_sha256` of what QA served.
3. One derivation, `frontend_engine.build.artifact_headers(files, api_base_url,
   csp_extensions)`, used by the build, trusted intake and the source adapter.
4. Intake (`worker/intake.accept_result`) re-derives from the **trusted job
   row** and **rejects** a candidate whose `_headers` differ (its QA evidence
   would describe a different policy); `judge_generative_candidate` then
   stores exactly those bytes.
5. Preview and production (`CloudflarePagesPreviewPublisher` /
   `CloudflarePagesPublisher`) materialize the stored artifact byte-for-byte;
   `wrangler pages deploy` applies its `_headers`.

### Visual QA (`frontend_engine/browser_qa.py`, stdlib-only)

Serves the artifact with its own `_headers` (never serving the file), loads
`/`, and adds findings `artifact_csp_applied`, `no_csp_violations`
(`securitypolicyviolation` events) and `no_failed_resources` (same-origin
4xx/5xx and failed requests). The sandboxed QA now stages `_headers` too.

### Acceptance (Nexo, local, real export)

- Intake re-derivation from `higgsfield-tanstack-static` == stored `_headers`;
  the CSP served on `/` == stored `_headers`.
- GWA browser QA on desktop/tablet/mobile/reduced-motion: CSP applied, 0 CSP
  violations, 0 failed resources, no page errors.
- 6/6 journey videos play from `blob:`; Cabinet Grotesk (Fontshare), Inter Tight
  and IBM Plex Mono load; PlatformContract and TruthContract: 0 findings.
- Visual diff vs the original export unchanged (0.00% at 19/20 positions).
- Remaining findings are pre-existing: 12 px mobile overflow (Higgsfield design);
  `no_broken_images` on `loading="lazy"` posters (browser QA does not scroll).

### Still open (H1.2)

- The execution host cannot build `higgsfield-tanstack-static` sources yet
  (bun toolchain + adapter in the worker); today they are built by the local
  adapter only.
- The worker path persists no Visual QA evidence row
  (`_record_visual_qa` finds no `GenerativeWebsiteArtifact` row) — pre-existing.
- ~~Sandboxed Visual QA cannot load Fontshare~~ — H1.2 stubs exactly the CSP-authorized
  origins offline; the live tier verifies the real font.
- ~~`no_broken_images` false positive for lazy images~~ — closed by H1.2.

## H1.2 — functional integration (Nexo)

**BusinessTruth.** A generated `src/platform/business.ts` (rebuilt every
build) binds the name, city, country, service names (by truth id, in the
ledger and the form), the owner-approved logo (or none), the canonical origin
and a truth-only JSON-LD (`HomeAndConstructionBusiness`; phone/email/address/
logo only if BusinessTruth has them; never ratings, reviews, prices, counts or
dates). A service the site presents but BusinessTruth lacks raises
`BusinessTruthGapError` (fail closed). Higgsfield's editorial copy is kept;
statements about how the business works are listed for owner confirmation.

**Leads.** `PublicLeadCreateRequest.details` (≤12 `{key,label,value}`, bounded,
unique keys) and `submission_id` (UUID). Migration `e5c1a7b3d9f2`: nullable
`leads.details` (JSON), `leads.client_submission_id` (UUID) and
`UNIQUE(business_id, client_submission_id)` — additive; existing rows/callers
unchanged. A retry of a stored submission gets the same `{received: true}`
with no second lead or notification (a savepoint covers the concurrent race).
`LeadRead`, the n8n payload (`details`, additive) and Studio's `LeadsList` show
the fields. The Platform SDK retries once on a network failure with the same
id. Rollout: the API and site builder must deploy together (a site built with
this SDK sends `submission_id`, which an older API would reject).

**Consent and legal (es).** Spanish platform banner (same ids and
byte-identical script → same CSP hash). Spanish privacy / legal notice
(*Aviso legal*, at `/terms`) / cookie pages from BusinessTruth; missing legal
identity renders as «no facilitado» and is a `launch_blocker` readiness
finding. The cookie page discloses Fontshare. No page claims compliance.

**Fonts.** ITF Free Font License v2.0 (Fontshare download `License/FFL.txt`,
sha256 `145e7fe2…`): §01 lets the Licensee self-host for its own sites; §02
forbids serving it for third parties through a SaaS platform and giving it to
service providers; §02/§05 forbid subsetting/format conversion. GWA therefore
keeps Cabinet Grotesk on the Fontshare API (the delivery the licence provides)
and does not copy the font anywhere. Inter Tight / IBM Plex Mono stay
self-hosted (OFL-1.1).

**Logo policy.** TruthContract now also treats an image as a logo when its own
or its enclosing link's `class`/`id` contains "brand" (never alt text). The
Higgsfield-generated mark is therefore shown only if BusinessTruth has an
owner-approved logo; Nexo has none, so the nav/legal pages use the wordmark.
Favicons derived from the mark are an `owner_review` finding.

**SEO.** Canonical and `og:url` on every page, owned Open Graph image
(`/og-image.jpg`, 1200×630, deterministically cropped from the export's own
final-chapter frame; no Higgsfield CDN), truth-only JSON-LD, platform robots
and sitemap (canonical origin).

**QA.** `browser_qa` scrolls to load lazy images and fails only on images that
completed without pixels or stay unloaded while rendered (never-rendered lazy
images are reported). Offline (sandboxed) QA answers exactly the https
style/font origins the artifact's own CSP authorizes with empty stubs
(recorded); everything else stays aborted. `visual_qa_state` evidence names
`artifact_sha256` + `headers_sha256` (`app/publishing/qa_evidence.py`);
Studio's `visual_qa_current` is false for evidence of any other artifact.

**Overflow.** The pre-existing 12 px mobile overflow came from the chapter
scrim (`.scroll-scrub__copy::before`, `inset: -3rem -2rem`); fixed with
`overflow-x: clip` on `.scroll-scrub` (mobile only) — no visible change,
sticky chapters unaffected.

### Acceptance (Nexo, local, real GWA API)

`scripts/h1_preview_qa.py` (throwaway SQLite, no provider configured, real
auth/public/Studio endpoints): 50/50. Visual diff vs the original export: only
the nav brand-mark band changes (desktop 0.18%, mobile ≈0.56%; the mobile
"Pedir presupuesto" nav button fits on one line once the mark is omitted).

### Blockers after H1.2

- **H2 (generalized adapter):** mappings are per export (patch fragments,
  service ids, claims list); a second export needs its own mapping or a
  content-contract convention in the Higgsfield brief.
- **Railway integration:** the execution host still builds only `gwa-astro`;
  Higgsfield exports need bun + the adapter on the worker, per-family
  prepared dependencies and the source-family job path.
- **Owner/legal input:** legal identity (legal name, NIF, address, privacy
  contact), legal text review, favicon approval and the listed claims.
- **External (Higgsfield):** no documented API/MCP/CLI for Supercomputer
  prompt-to-website generation or export; exports are manual.

## Reproduce

```bash
cd apps/api
uv run python scripts/h1_higgsfield_adapter.py --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-h1/run
uv run python scripts/h1_preview_qa.py --work-root /tmp/gwa-h1/run --spike-visual /path/to/spike/visual
```
