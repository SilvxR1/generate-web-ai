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

**No server-held Higgsfield credential (dev/local path only).**
`HiggsfieldCliCreativeDirector` uses the `higgsfield` CLI's own
already-authenticated local OAuth session (`higgsfield auth login`) rather
than a server-held credential — the CLI's token is never read, printed, or
logged by this codebase. This remains an explicit, documented
**limitation, not a feature** for that path: it is not safe to run
unattended in a production deployment (no interactive session exists
there to hold the OAuth token) — see `docs/higgsfield-integration.md`. It
defaults fully disabled (`higgsfield_cli_enabled=False`) and is never
selected when the production credential below is configured.

## P2.1: Production Higgsfield REST integration

**Server-side API key pair, never a browser session.**
`HiggsfieldApiCreativeDirector` (`app.creative.higgsfield.api_client`)
authenticates with `HIGGSFIELD_API_KEY_ID`/`HIGGSFIELD_API_KEY_SECRET` —
`Authorization: Key <ID>:<SECRET>` — safe to run unattended, unlike the
CLI/OAuth path above. This is the real, documented Higgsfield mechanism
(confirmed against the official OpenAPI spec, see
`docs/higgsfield-integration.md`), not an undocumented workaround.

**No secret leakage.** The Authorization header value is built once per
client instance and never appears in any exception message, log line, or
the `raw` response dict this client returns — `HiggsfieldApiError`
messages include only the HTTP status code and a length-bounded tail of
the response body, never request headers.

**SSRF / unsafe outgoing reference URLs.**
`app.creative.higgsfield.api_client._validate_reference_url` rejects any
`image_url` sent to Higgsfield that isn't `https://` with a real public
hostname — no `file://`/`javascript:` scheme, no bare private/loopback/
link-local IP, no `localhost`. `BusinessAsset.storage_url` values are
always generated internally (`app.storage.keys.generate_storage_key`),
never taken from raw user input, but this check stays as defense in
depth, the same discipline `app.creative.higgsfield.cli.resolve_local_reference`
already applies on the CLI path.

**No arbitrary callback URLs.** P2.1 v1 deliberately uses polling, not
webhooks (`GET /requests/{id}/status`) — there is no webhook-receiver
endpoint in this codebase to worry about accepting an arbitrary callback
URL from, and no incoming payload from Higgsfield is ever trusted without
this process itself having issued the `request_id`/`status_url` first
(`HiggsfieldApiClient.get_status` only ever polls a URL Higgsfield itself
returned to a `submit()` this process made).

**No double-spend retries.** `HiggsfieldApiClient.submit` (the
credit-consuming POST) is never retried automatically — only the
read-only, unbilled `GET /requests/{id}/status` poll retries a bounded
number of times on a transient network error. A `create_directions`/
`develop_direction` call that fails mid-workflow stops and returns
whatever candidates already completed (`_HiggsfieldDirectorBase`'s shared
`try`/`except` per iteration) rather than restarting the whole exploration.

**Credit-budget enforcement is unchanged and still pre-flight**
(`app.domain.creative.budget.CreativeBudget.record_spend`) — every call
is costed (via a configured estimate; see `docs/higgsfield-integration.md`
for why no real estimate endpoint exists) and checked against the caller's
hard limit *before* the request is sent, never after.

**Generated customer websites never receive Higgsfield/Anthropic
credentials.** The AI Frontend Engineer's own prompt context carries no
provider credential of any kind (unchanged from P2 — see
`app.creative.frontend_engine.anthropic_engine`'s own docstring), and
`CreativeDirection.provider_metadata`/`generation_metadata` (which do
reach the frontend engine's prompt as reference material) never contain a
key, token, or the raw Higgsfield API response beyond a `job_id` and a
public result URL.

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

## A2: Authentication & Authorization

Full design writeup: `docs/a2-authentication-authorization.md`. This
section is the security review performed before opening the PR.

**Session fixation.** A session token is generated fresh on every
successful login (`app.auth.service._create_session`) — there is no path
that reuses or "upgrades" a pre-login token into an authenticated one, so
an attacker cannot plant a token before a victim logs in and inherit their
session afterward.

**Token entropy/storage.** Session tokens are `secrets.token_urlsafe(32)`
— 256 bits from the OS CSPRNG. Only a SHA-256 digest (`token_hash`) is
persisted; the raw token exists only in the HttpOnly cookie and is never
written to the database, a log line, or an exception message. CSRF tokens
use the same generator and entropy.

**Password hashing.** Argon2id via `argon2-cffi`'s `PasswordHasher`
defaults (time_cost=3, memory_cost=64 MiB, parallelism=4 as of
argon2-cffi's current release) — chosen over bcrypt specifically to avoid
bcrypt's silent 72-byte password truncation. Never a hand-rolled scheme.

**Cookie flags.** `HttpOnly` always (session token never reaches JS).
`Secure`/`SameSite` are environment-computed (`app.auth.cookies`) based on
a real topology investigation, not a default left unexamined — see that
module's own docstring and `docs/a2-authentication-authorization.md`'s
Cookie flags section.

**CSRF.** A per-session token, returned only in the JSON response body
(never the cookie), required as `X-CSRF-Token` on every non-safe-method
authenticated request, compared with `hmac.compare_digest`. Deliberately
not "we use SameSite" — production's cross-site topology requires
`SameSite=None`, which forfeits that protection on its own (see
`app.dependencies._check_csrf` and the CSRF section of the design doc).

**CORS interaction.** `CORSMiddleware` already restricts `allow_origins`
to a specific allowlist (never `*`) with `allow_credentials=True` — a
prerequisite for cookies to work cross-origin at all, and also what makes
the CSRF token's "an attacker's page can trigger a request but can't read
the response body" property hold: `allow_credentials=True` with a
wildcard origin is rejected by browsers outright, so this configuration
was already forced into the safe shape before A2 existed.

**Brute-force protection.** `POST /auth/login` is rate-limited
(`auth_login_rate_limit_per_minute`, default 5/min per IP, the same
`InMemoryRateLimiter` mechanism as the pre-existing lead/asset-upload
limits and sharing its known per-process limitation — see Rate limiting
above).

**Error enumeration.** Unknown email, wrong password, and a password-less
account all return the identical `401 invalid_credentials` response, and
a real Argon2 verify always runs (against a fixed decoy hash for an
unknown email) so response timing can't distinguish them either — see
`login_with_password`'s own docstring.

**Tenant enumeration.** `unknown_tenant` (404) is the same error for "no
such Tenant row" and "a real Tenant this authenticated user has no
`TenantAccess` grant for" — an authenticated caller can never learn which
tenant UUIDs are real ones they simply lack access to.

**Logging/redaction.** No route or service logs a password, session
token, cookie value, or password hash — verified by inspection of every
`app.auth.*`/`app.routers.auth`/`app.dependencies` code path (none of them
call any logger with those values) and by `test_password_and_hash_never_
appear_in_login_response` (response body, not logs, but the same
discipline: nothing sensitive is ever serialized outward).

**Cross-tenant access.** Full User A/User B/Tenant A/Tenant B matrix in
`tests/test_a2_tenant_authorization_matrix.py`, covering business, assets,
leads, reviews, analytics, creative directions, website drafts, domains,
website versions/rollback, and business deletion — every category denies
with `unknown_tenant` and never reaches tenant-scoped data.

**Destructive/public/internal endpoints.** Business deletion requires the
same session+TenantAccess+CSRF boundary as every other mutating route (no
separate, weaker path). `/public/businesses/{id}/leads`,
`.../events`, and `/health` remain unauthenticated and untouched
(`tests/test_a2_public_internal_regression.py`). `/internal/*` remains
gated solely by `X-Internal-Automation-Token`, with no session concept
introduced — same file, explicit regression tests.

## A3 / A3.1: Application Security Audit & Remediation

Full audit report and severity classification: see the A3 session report
(not committed as a standalone doc). This section documents the concrete
policies the A3.1 remediation put in place — not a claim that the
application is "fully secure," only what is actually implemented and
tested as of this commit.

**SVG/image upload policy (F-01).** `image/svg+xml` is no longer accepted
for any business asset upload (upload, batch upload, or replace) — SVG
support was removed entirely, not sanitized, since an SVG is fundamentally
an XML+script document wearing an image extension and this codebase has
no sanitizer. LOGO and IMAGE asset kinds are validated against their
**actual bytes** (`app.storage.image_validation.validate_raster_image`):
a real magic-byte sniff restricted to JPEG/PNG/WebP/GIF, a Pillow decode
constrained to the sniffed format only, and the same
`MAX_IMAGE_SIDE`/`MAX_IMAGE_PIXELS` decompression-bomb bounds already
established in `app.domain.creative.brand_intelligence`. The client's
declared Content-Type header is never trusted for these two kinds — only
the real, decoded type is checked against the allowlist. VIDEO/DOCUMENT
kinds are unaffected (still header-only, outside this finding's scope).

**SSRF / redirect policy (F-02).** `app.monitoring.checks.check_http`
(the website health checker) follows redirects manually, one hop at a
time, and re-validates **every** redirect destination through
`app.security.ssrf.validate_outbound_url` before ever requesting it — a
public URL that redirects to `localhost`, a private IPv4/IPv6 range,
link-local, or a cloud metadata address is never followed, reported
identically to any other unreachable site. A legitimate public-to-public
redirect (bare domain → www, http → https) is still followed normally, up
to 5 hops, so real business websites that redirect are not misreported as
down.

**Paid-provider rate limits (F-03).** `POST .../creative-generations`,
`POST .../creative-directions`, and `POST .../creative-directions/{id}/develop`
— the three routes that trigger a real Higgsfield/Anthropic provider
call — are now rate-limited via the same `rate_limit_dependency`
infrastructure as login/asset-upload/website-health/public-lead/public-
analytics (`creative_generation_rate_limit_per_minute`,
`creative_direction_rate_limit_per_minute`,
`creative_direction_develop_rate_limit_per_minute`, all in
`app.config.Settings`, defaults 5/5/10 per minute). This sits alongside —
never in place of — `CreativeBudget`'s existing per-request fan-out cap:
the budget bounds one request's own cost, the rate limit bounds how often
a caller can make that request at all. Tenant authorization
(`get_current_tenant_id`) still runs independently and is unaffected by
the rate limiter's presence.

**Astro dependency (F-04).** Every workspace package's `astro` pin was
bumped from `7.2.3` to `7.2.8`, resolving GHSA-26w7-cxv4-gfx2 (a critical
RCE via AVIF image optimization). Verified: exactly one `astro` version
resolves across the whole workspace (`pnpm why astro`), every
Astro-building package's own tests pass, and all three real site builds
(`site-template`, `reforma-casa-valencia`, `sacri-barber` — the latter
via the `@astrojs/cloudflare` adapter) complete successfully.

**Remaining dependency advisories.** `fast-uri`, `sharp`, `js-yaml`,
`svgo`, and `devalue` were bumped to their patched versions via a
targeted `pnpm-workspace.yaml` `overrides` block — every one is a deep,
dev/build-time-only transitive dependency (Astro's own toolchain,
`@astrojs/cloudflare`'s local Workers emulation, JSON-schema tooling),
never part of a served runtime, and each bump is patch/minor with no
breaking-change surface (confirmed: `pnpm audit` now reports 0
critical/0 high). `vitest`/`@vitest/mocker`'s advisory (moderate, a path-
traversal issue in Vitest's own dev/browser-mode file serving — not
exposed by this repo's CI usage) requires a Vitest **major** version
bump (3.x → 4.x) and was deliberately left alone as out of scope for this
focused security remediation — tracked as a P2 hardening item for a
dedicated, separately-tested upgrade.

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
