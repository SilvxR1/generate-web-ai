# Security posture (P0)

This documents the security-relevant decisions made in the P0 Production
Readiness phase — what's implemented in code, and what still needs a
repository owner to configure through GitHub's own UI (this environment
has no credentials to do that safely on your behalf).

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
