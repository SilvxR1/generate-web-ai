"""The public API origin a generated site's browser scripts call (A8.3.4-P0).

A deterministic site's contact form and analytics beacon POST to
`{PUBLIC_API_BASE_URL}/public/businesses/{id}/leads|events`, an Astro
build-time constant (apps/site-builder's Layout/LeadSubmission/Analytics).
Production builds ran with it unset, so every published deterministic site
rendered `apiBaseUrl = ""` and its lead form silently did nothing.

The origin is not a second setting. It is the same operator-configured
value the rest of the backend already trusts as "where this API is
reachable" (settings.internal_api_base_url, also used for the generative
engine's injected platform config and for absolute asset URLs). An explicit
PUBLIC_API_BASE_URL in the process environment still takes precedence, for
an operator who needs to point sites at a different public origin.

`public_origin_problem` is the single validator for that value, used both
before injecting it into a build and by PlatformContract on the rendered
artifact. It uses the same stdlib `urlsplit` parser as app.security.ssrf,
but is purely syntactic: a browser calls this origin, the backend never
fetches it, so there is no DNS resolution and local development
(`http://localhost:8000`) stays valid.
"""

import os
from urllib.parse import urlsplit

from app.config import settings

_LOCAL_DEV_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


def public_origin_problem(value: str | None) -> str | None:
    """None when `value` is a usable public API origin; otherwise a short
    reason. Accepts `https://host[:port]` (optionally with a trailing "/"),
    and plain `http://` only for local development hosts. Rejects other
    schemes (javascript:, data:, file:, ...), embedded credentials, paths,
    queries and fragments."""
    if not value or not value.strip():
        return "no public API origin is configured"
    try:
        parts = urlsplit(value.strip())
        port = parts.port  # raises ValueError for a malformed port
    except ValueError:
        return "the public API origin is malformed"
    del port
    if parts.scheme not in ("https", "http"):
        return f"scheme {parts.scheme!r} is not allowed for the public API origin"
    if not parts.hostname:
        return "the public API origin has no host"
    if parts.username is not None or parts.password is not None:
        return "the public API origin must not contain credentials"
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return "the public API origin must be a bare origin (no path, query or fragment)"
    if parts.scheme == "http" and parts.hostname not in _LOCAL_DEV_HOSTS:
        return "the public API origin must use https outside local development"
    return None


def resolve_public_api_base_url() -> str:
    """The origin to bake into a site build: an explicit PUBLIC_API_BASE_URL
    if the environment sets one, otherwise settings.internal_api_base_url.
    Returned without a trailing slash; validity is checked separately (by
    PlatformContract on the built artifact), never silently fixed here."""
    explicit = os.environ.get("PUBLIC_API_BASE_URL")
    value = explicit if explicit is not None else settings.internal_api_base_url
    return value.strip().rstrip("/")
