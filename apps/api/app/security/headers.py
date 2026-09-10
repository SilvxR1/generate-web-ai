"""SecurityHeadersMiddleware — a centralized place to set response
headers that harden this API against clickjacking, MIME-sniffing, and
overly permissive browser features (Phase 4). This is the JSON API's own
headers, not the generated customer websites' — those are static builds
served by Cloudflare Pages, a separate process entirely; see
app.publishing.build's `_headers` file generation for that side.

No CSP is emitted here: this API returns JSON (browsers don't execute
script from a JSON response) except FastAPI's own /docs, /redoc pages,
which load their assets from a CDN — a strict CSP there would break them
for no real security gain (nothing user-supplied is ever rendered as HTML
by this service). Environment-aware: HSTS is only ever added when
`settings.environment == "production"`, since local/dev almost never runs
behind real HTTPS and a stray HSTS header there can lock a browser out of
plain-HTTP localhost for its configured max-age.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, is_production: bool) -> None:
        super().__init__(app)
        self._is_production = is_production

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in _BASE_HEADERS.items():
            response.headers.setdefault(name, value)
        if self._is_production:
            # 2 years, includes subdomains — Railway/production always
            # terminates HTTPS in front of this process; only ever set
            # when we know that's true.
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response
