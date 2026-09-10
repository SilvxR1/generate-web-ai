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
