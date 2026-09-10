"""generate_headers_file — the customer-website counterpart to
app.security.headers.SecurityHeadersMiddleware (Phase 4). Generated sites
are static builds served by Cloudflare Pages, a separate process from
this API entirely, so a Starlette middleware can't reach them — Cloudflare
Pages instead reads a literal `_headers` file at the root of the deployed
output and applies its rules to matching paths (Cloudflare's own,
documented convention; see
https://developers.cloudflare.com/pages/configuration/headers/). This
function produces that file's content; app.publishing.build.build_site
adds it to every WebsiteArtifact so every deploy carries it automatically
— no manual step per client site.

HSTS is included unconditionally here (unlike the API's own
environment-gated middleware): Cloudflare Pages only ever serves over
HTTPS — there is no "local dev" deployment of a generated site to
accidentally break with a stray HSTS header.

The CSP is deliberately conservative rather than maximally strict:
`img-src` allows any `https:` origin because a business's real photos
(app.db.models.business_asset.BusinessAsset.storage_url) may be hosted
anywhere, not only this backend's own /uploads — Section 1's "real
business content" must never be silently blocked by a security policy.
`style-src` allows `'unsafe-inline'` because Astro's compiled output can
include small inline critical-CSS style blocks.

`script-src` deliberately does NOT use `'unsafe-inline'`: a real build
(tests/test_site_builder_integration.py) showed packages/ui's own
checkbox-group-validation and scroll-reveal behavior compile to small
inline `<script type="module">` blocks — real, legitimate site behavior,
not something to break. Instead, app.publishing.build.build_site passes
in the SHA-256 hash of each inline script actually present in this
specific build (computed fresh every time, since Astro's compiled output
can change between dependency versions) via `script_hashes`, so the CSP
allow-lists exactly those bytes and nothing else — a real XSS payload
injected through business/user content would produce a *different* inline
script with a different hash and stay blocked.
"""

_BASE_CSP_DIRECTIVES = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_OTHER_HEADER_LINES = [
    "X-Content-Type-Options: nosniff",
    "X-Frame-Options: DENY",
    "Referrer-Policy: strict-origin-when-cross-origin",
    "Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Strict-Transport-Security: max-age=63072000; includeSubDomains",
]


def generate_headers_file(*, script_hashes: frozenset[str] = frozenset()) -> bytes:
    """Cloudflare Pages' `_headers` file format: a path pattern line
    followed by indented `Header: value` lines. `/*` applies to every
    route on the site, including the legal pages (Section 17) and any
    future page — there's currently no reason for any route to need a
    different policy. `script_hashes` are bare base64 SHA-256 digests
    (no `sha256-` prefix, no quotes) of every inline `<script>` this
    specific build actually contains — see app.publishing.build's
    extraction of them."""
    script_src_sources = ["'self'", *(f"'sha256-{digest}'" for digest in sorted(script_hashes))]
    csp = f"script-src {' '.join(script_src_sources)}; {_BASE_CSP_DIRECTIVES}"
    lines = ["/*", f"  Content-Security-Policy: {csp}", *(f"  {line}" for line in _OTHER_HEADER_LINES)]
    return ("\n".join(lines) + "\n").encode("utf-8")
