# Security posture (P0, extended in P2)

This documents the security-relevant decisions made in the P0 Production
Readiness phase — what's implemented in code, and what still needs a
repository owner to configure through GitHub's own UI (this environment
has no credentials to do that safely on your behalf). See "P2: Generative
Creative Engine" below for the additions made when the Higgsfield
creative-director/generative pipeline was introduced.

## P2: Generative Creative Engine

**Higgsfield CLI subprocess safety**
(`app.creative.higgsfield.cli.HiggsfieldCli`): every call is a real
`subprocess.run([binary, *args, "--json"], ...)` argv list — never
`shell=True`, never a string-interpolated shell command — so arbitrary
business text reaching a `--prompt` argument (a business description, a
target-customer string, all of which are user-supplied and untrusted)
can never break out into shell command injection regardless of content.
Verified directly by `tests/test_higgsfield_cli_director.py::test_cli_never_uses_a_shell_string`.

**No server-held Higgsfield credential.** `HiggsfieldCreativeDirector`
uses the `higgsfield` CLI's own already-authenticated local OAuth session
(`higgsfield auth login`) rather than an `HIGGSFIELD_API_KEY` — the CLI's
token is never read, printed, or logged by this codebase. This is an
explicit, documented **limitation, not a feature**: it means this
integration path is not yet safe to run unattended in a production
deployment (no interactive session exists there to hold the OAuth token)
— see `docs/higgsfield-integration.md`. It defaults fully disabled
(`higgsfield_cli_enabled=False`).

**Workspace path-traversal guard**
(`app.creative.higgsfield.cli.resolve_local_reference`): a
`BusinessAsset.storage_url` is only ever resolved to a local reference
file after confirming the resolved path stays under the configured
`local_storage_dir` root (`Path.relative_to` check) — a crafted/corrupted
storage URL containing `..` segments can never cause a read outside that
directory.

**Factual-safety boundary carried through, never re-invented per
provider** (`app.creative.factual_safety.constraints_for_brief`): every
`CreativeDirection`, from either director, carries the identical
prohibited-claims list (pricing, years of experience, certifications,
reviews, guarantees, addresses, hours, shipping, delivery times,
materials, customer counts, awards, availability, ecommerce) and only
ever states `factual_claims` traceable to a real `CreativeBrief` field.

**PlatformContract as a security boundary, not just a QA one**
(`app.qa.platform_contract`): a lead form that exists in generated markup
but isn't wired to the platform's own submission path is a BLOCKING
violation — this is what prevents a generated site from silently routing
lead data somewhere uncontrolled, or presenting a form that goes nowhere.

**Known, not-yet-built surface — the AI Frontend Engineer.** This P2
pass designed but did not implement the Generative Frontend Engine (the
component that would have an LLM write actual Astro/TypeScript/CSS files
into an isolated workspace and build them). No claim is made about its
security posture because it doesn't exist in this codebase yet. Its
design (isolated per-generation workspace directory, a hard dependency
allowlist checked before any `pnpm install`, no production secrets in
its prompt context, explicit prompt-injection framing treating business/
scraped content as data never instructions) is recorded in this PR's
final report as the next implementation's starting point — anyone
building it should treat generated file paths as untrusted input
(reject `..`/absolute paths before writing) and never grant that engine
network egress beyond the npm registry.

**Pre-existing, unrelated finding**: `git push` on this branch surfaced
GitHub's own Dependabot alert (32 open vulnerabilities on `main`, mostly
transitive JS dependencies) — pre-existing on the default branch, not
introduced by this work, and out of scope for this PR to remediate.

## Secrets

A full audit of git-tracked content (current tree and full history) found
no committed secrets, no committed `.env` file (`.env`/`.env.*` are
git-ignored, `.env.example` carries only variable names), and no
hardcoded credentials anywhere in application code. The one match for a
"password"-shaped pattern is a deliberately fake test fixture
(`tests/test_smtp_isolation.py`, `password="not-a-real-secret"`). No
rotation is required.

## API security headers (`app.security.headers.SecurityHeadersMiddleware`)

Applied to every response from this backend:

| Header | Value | Why |
| --- | --- | --- |
| `X-Content-Type-Options` | `nosniff` | Stops a browser from MIME-sniffing a response into executing as something other than its declared type. |
| `X-Frame-Options` | `DENY` | This API is never meant to be framed. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Don't leak full URLs (which can carry query params) to third-party origins. |
| `Permissions-Policy` | camera/microphone/geolocation denied, `interest-cohort=()` | This API uses none of these; deny by default. |
| `Strict-Transport-Security` | 2-year max-age, only when `ENVIRONMENT=production` | Never set in local dev, where HTTPS often isn't in front of the process. |

No CSP is set on the API itself — it returns JSON, not HTML a browser
would execute script from (the one exception, FastAPI's own `/docs`, is
low-stakes and would break under a strict CSP for no real security gain).

## Customer website security headers

Generated customer sites are static builds served by Cloudflare Pages —
a separate process this middleware can't reach. Instead,
`app.publishing.security_headers.generate_headers_file` writes a
Cloudflare Pages `_headers` file into every build
(`app.publishing.build.build_site`), carrying the same base headers plus
a real `Content-Security-Policy`:

```
default-src 'self';
img-src 'self' data: https:;
style-src 'self' 'unsafe-inline';
script-src 'self' 'sha256-<hash>' [...];
font-src 'self' https://fonts.gstatic.com data:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
```

`img-src` allows any `https:` origin because a business's real photos may
be hosted anywhere (Section 1: real content is never blocked). `script-src`
does **not** use `'unsafe-inline'` — a real build was found to emit two
legitimate inline `<script>` blocks (packages/ui's checkbox-group
validation and scroll-reveal behavior), so their exact SHA-256 hashes are
computed fresh per build and allow-listed instead; an actual injected
script would hash differently and stay blocked. `HSTS` is unconditional
here (unlike the API above) — Cloudflare Pages never serves plain HTTP.

## Rate limiting (`app.security.rate_limit`)

`RateLimiter` is an interface; `InMemoryRateLimiter` (a per-process
sliding window) is the only implementation today, applied to:

- `POST /businesses/{id}/assets/upload` — `asset_upload_rate_limit_per_minute` (default 20/min per IP)
- `POST /public/businesses/{id}/leads` — `public_lead_rate_limit_per_minute` (default 10/min per IP)

**Known limitation:** `InMemoryRateLimiter` is process-local. If this API
ever runs as more than one instance/worker, each tracks its own count
independently — the effective limit becomes `limit × instance count`.
Swap in a Redis- or Cloudflare-KV-backed `RateLimiter` implementation
before scaling past one instance; no caller code needs to change.

## Tenant isolation

Verified (and covered by tests) for every route in `app/routers/`: every
handler except `health` (no data) and `/internal/*` (its own shared-token
auth) requires `get_current_tenant_id`, and every repository call is
scoped by both `tenant_id` and `business_id`. Cross-tenant access returns
404, never revealing existence. `POST /public/businesses/{id}/leads`
(P0's one deliberately-public endpoint) derives `tenant_id` from the
`Business` row itself server-side — a caller can never submit one.

## Manual GitHub configuration still required

These are GitHub repository settings this environment cannot verify or
enable without owner access — **do not assume they're on** until you've
checked:

1. **Secret scanning + push protection** — Settings → Code security →
   enable both. Catches a credential before it's ever pushed.
2. **Branch protection on `main`** — require the `CI` workflow's
   `backend` and `frontend` jobs to pass before merge; consider requiring
   PR review.
3. **Dependabot alerts** — Settings → Code security → enable (the
   `.github/dependabot.yml` in this repo only opens *update* PRs; alerts
   are a separate toggle).
4. Confirm no repository secrets exist for `HIGGSFIELD_*`, Cloudflare, or
   any other provider that CI could accidentally pick up — this CI
   workflow never references any secret, by design.
