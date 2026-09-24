"""PublicEndpointCORSMiddleware (A8.3.4-P0): CORS for the two anonymous
endpoints a generated customer website's browser scripts call —
POST /public/businesses/{id}/leads and POST /public/businesses/{id}/events.

The app-wide CORSMiddleware (app.main) is deliberately strict and
credentialed: it only admits the Studio origins listed in CORS_ORIGINS,
because Studio calls authenticated, cookie-bearing endpoints. Customer sites
are served from arbitrary origins (each business's *.pages.dev project and
its own custom domain), so their contact-form and analytics fetches were
rejected at the preflight (HTTP 400, no Access-Control-Allow-Origin): lead
capture could not work even with the right API origin baked in.

These two endpoints have a different security model: they are anonymous
(no session, no cookie — both scripts use `fetch` without credentials),
business-scoped by the path, validated and rate limited per IP
(app.security.rate_limit), and spam-filtered. So they get NON-credentialed
CORS: `Access-Control-Allow-Origin: *` without
`Access-Control-Allow-Credentials`, limited to POST with a JSON content
type. Browsers never attach cookies to such requests, so no Studio session
can be used through them. Every other route keeps the strict credentialed
policy untouched. CORS is not an abuse control; rate limiting is.
"""

import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PUBLIC_BROWSER_ENDPOINT = re.compile(r"^/public/businesses/[^/]+/(?:leads|events)/?$")

_ALLOW_HEADERS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"POST, OPTIONS"),
    (b"access-control-allow-headers", b"content-type"),
    (b"access-control-max-age", b"600"),
]


def _is_public_browser_endpoint(scope: Scope) -> bool:
    return scope["type"] == "http" and bool(_PUBLIC_BROWSER_ENDPOINT.match(scope.get("path", "")))


class PublicEndpointCORSMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_public_browser_endpoint(scope):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        if scope["method"] == "OPTIONS" and b"access-control-request-method" in headers:
            await send({"type": "http.response.start", "status": 204, "headers": list(_ALLOW_HEADERS)})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_public_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Replace whatever the credentialed middleware added (it may
                # emit Allow-Credentials without an allowed origin).
                kept = [(k, v) for k, v in message.get("headers", []) if not k.lower().startswith(b"access-control-")]
                message = {**message, "headers": [*kept, (b"access-control-allow-origin", b"*")]}
            await send(message)

        await self.app(scope, receive, send_with_public_cors)
