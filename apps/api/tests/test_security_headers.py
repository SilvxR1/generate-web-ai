"""app.security.headers.SecurityHeadersMiddleware (the API's own
responses) and app.publishing.security_headers.generate_headers_file
(customer sites' Cloudflare Pages `_headers` file) — Phase 4."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.publishing.security_headers import generate_headers_file


@pytest.fixture()
def client():
    return TestClient(app)


def test_api_responses_carry_the_base_security_headers(client: TestClient):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in response.headers


def test_hsts_is_absent_outside_production(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    assert settings.environment != "production"
    response = client.get("/health")

    assert "Strict-Transport-Security" not in response.headers


def test_hsts_is_present_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "environment", "production")
    from app.main import create_app

    prod_app = create_app()
    response = TestClient(prod_app).get("/health")

    assert "Strict-Transport-Security" in response.headers


def test_error_responses_still_carry_security_headers(client: TestClient):
    response = client.get("/businesses", headers={"X-Tenant-Id": "not-a-uuid"})

    assert response.status_code == 400
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_customer_site_headers_file_has_no_unsafe_inline_script_source():
    content = generate_headers_file().decode()

    assert "'unsafe-inline'" not in content.split("script-src")[1].split(";")[0]
    assert "script-src 'self'" in content


def test_customer_site_headers_file_allow_lists_real_inline_script_hashes():
    content = generate_headers_file(script_hashes=frozenset({"abc123=="})).decode()

    assert "'sha256-abc123=='" in content
    assert "X-Frame-Options: DENY" in content
    assert "Strict-Transport-Security" in content


# --- A8.3.4-P0.2: connect-src must allow the site's public API origin ------


def _csp_directives(content: str) -> dict[str, list[str]]:
    policy = next(line for line in content.splitlines() if "Content-Security-Policy:" in line).split(":", 1)[1]
    return {tokens[0]: tokens[1:] for tokens in (part.split() for part in policy.split(";")) if tokens}


def test_a_valid_public_api_origin_is_the_only_extra_connect_src_source():
    content = generate_headers_file(public_api_origin="https://API.example.com/").decode()

    assert _csp_directives(content)["connect-src"] == ["'self'", "https://api.example.com"]


@pytest.mark.parametrize(
    "origin", [None, "", "http://api.example.com", "javascript:alert(1)", "https://a.example.com/x"]
)
def test_an_unusable_origin_leaves_connect_src_at_self(origin):
    content = generate_headers_file(public_api_origin=origin).decode()

    assert _csp_directives(content)["connect-src"] == ["'self'"]


def test_the_api_origin_never_broadens_or_weakens_any_other_directive():
    without = _csp_directives(generate_headers_file(script_hashes=frozenset({"abc=="})).decode())
    with_origin_content = generate_headers_file(
        script_hashes=frozenset({"abc=="}), public_api_origin="https://api.example.com"
    ).decode()
    with_origin = _csp_directives(with_origin_content)

    assert {k: v for k, v in with_origin.items() if k != "connect-src"} == {
        k: v for k, v in without.items() if k != "connect-src"
    }
    assert list(with_origin) == list(without)  # directive order unchanged
    for wildcard in ("*", "https:", "http:", "'unsafe-inline'", "'unsafe-eval'"):
        assert wildcard not in with_origin["connect-src"]
    for line in ("X-Frame-Options: DENY", "X-Content-Type-Options: nosniff", "Strict-Transport-Security"):
        assert line in with_origin_content
    assert with_origin["frame-ancestors"] == ["'none'"]
