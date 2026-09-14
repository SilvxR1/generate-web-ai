"""_public_base_url (app.routers.creative) — Phase 8 hotfix: production
was observed returning `http://...` asset URLs even though Railway serves
HTTPS externally, because request.base_url reflects whatever scheme the
ASGI server itself received the request over (the scheme Railway's own
proxy forwards internally), not necessarily what a real browser used.
Verifies the three-step resolution order in isolation — no TestClient, no
real network — using a synthetic Starlette Request built from a raw ASGI
scope."""

import pytest
from starlette.requests import Request

from app.config import settings
from app.routers.creative import _public_base_url


def _request(*, scheme: str = "http", headers: list[tuple[str, str]] | None = None) -> Request:
    scope = {
        "type": "http",
        "scheme": scheme,
        "server": ("testserver", 443 if scheme == "https" else 80),
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or [])],
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_internal_api_base_url(monkeypatch: pytest.MonkeyPatch):
    # Every test in this module sets its own value explicitly — never
    # inherits whatever a developer's own environment happens to have
    # configured (see tests/test_asset_upload_api.py's own fixture for
    # why that matters).
    monkeypatch.setattr(settings, "internal_api_base_url", "http://localhost:8000")


def test_prefers_a_real_configured_public_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "internal_api_base_url", "https://api.cositasypuntos.example.com")

    assert _public_base_url(_request()) == "https://api.cositasypuntos.example.com"


def test_configured_value_is_rstripped_of_a_trailing_slash(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "internal_api_base_url", "https://api.example.com/")

    assert _public_base_url(_request()) == "https://api.example.com"


def test_honors_a_trusted_forwarded_proto_when_nothing_is_configured():
    """The exact production bug this hotfix fixes: Railway's proxy
    forwards the request internally over plain HTTP even though it
    itself terminates HTTPS at the edge — X-Forwarded-Proto is Railway's
    own signal of the real external scheme."""
    request = _request(headers=[("X-Forwarded-Proto", "https")])

    assert _public_base_url(request) == "https://testserver"


def test_falls_back_to_request_base_url_for_local_development():
    """No configured override, no forwarded-proto header — exactly local
    development, where request.base_url is already correct as-is. Never
    a hardcoded https://."""
    assert _public_base_url(_request()) == "http://testserver"


def test_forwarded_proto_never_downgrades_an_already_https_base_url():
    """A defensive edge case: this function only ever corrects an http
    base_url using a forwarded https, never the reverse — an
    already-https request.base_url is never rewritten to http."""
    request = _request(scheme="https", headers=[("X-Forwarded-Proto", "http")])

    assert _public_base_url(request) == "https://testserver"


def test_uses_only_the_first_value_of_a_multi_hop_forwarded_proto_header():
    request = _request(headers=[("X-Forwarded-Proto", "https, http")])

    assert _public_base_url(request) == "https://testserver"
