"""Session cookie attributes (A2) — the one place `SameSite`/`Secure` are
decided, so the reasoning lives in exactly one function instead of being
duplicated at every `set_cookie`/`delete_cookie` call site.

TOPOLOGY THIS WAS DESIGNED AGAINST (see docs/a2-authentication-authorization.md
for the full write-up): Studio has no production hosting of its own yet
(only a dev-only Dockerfile running `vite dev`) and is expected to be served
from a different registrable domain than this API's own Railway domain
whenever it does — a genuinely cross-site relationship, not just
cross-port. `SameSite=Lax` would silently never send the cookie on a
cross-site fetch/XHR (it only rides along on top-level navigation), which
would look like "login succeeds, every subsequent request 401s" — a
confusing failure mode to debug in production. `SameSite=None` is required
for the cross-site case and is what production uses; it does require
`Secure`, which in turn requires HTTPS (true of every real deployment,
including Railway's own https that Studio's future host would be calling
into). Local development runs Studio and the API on `localhost` at
different ports, which IS same-site for cookie purposes (SameSite compares
the registrable domain, never the port), so `SameSite=Lax` + non-`Secure`
is correct there and lets a plain `http://localhost:8000` dev API keep
working without a self-signed certificate.

Because `SameSite=None` deliberately gives up SameSite's own CSRF
protection for the production case, CSRF is handled separately and
unconditionally (see app.dependencies' CSRF check) — this module makes no
CSRF claims of its own.
"""

from fastapi import Response

from app.config import settings


def _is_production() -> bool:
    return settings.environment == "production"


def set_session_cookie(response: Response, *, raw_token: str, max_age_seconds: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=_is_production(),
        samesite="none" if _is_production() else "lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=_is_production(),
        samesite="none" if _is_production() else "lax",
        path="/",
    )
