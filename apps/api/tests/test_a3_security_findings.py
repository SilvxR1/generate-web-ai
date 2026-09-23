"""A3 application-security-audit findings.

A3-UPLOAD-1 (SVG upload / stored content injection) was remediated in
A3.1 — see app.storage.image_validation and app.routers.creative's
_validate_uploaded_content. The test below now asserts the FIXED
behavior (rejection) and stays as permanent regression coverage;
comprehensive coverage for the fix itself (valid JPEG/PNG/WebP, fake-MIME
rejection, mismatched-header acceptance) lives in
tests/test_asset_upload_api.py alongside the rest of the upload surface.

A3-SSRF-1 (SSRF-via-redirect in the website health checker) was
remediated in A3.1 — see app.monitoring.checks.check_http. The test
below now asserts the FIXED behavior (no redirect following).

Neither test is a "trip-wire for an unfixed vulnerability" anymore; both
simply pin the remediated behavior in place, same as any other
regression test.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_rate_limiter, get_session
from app.domain.enums import HealthStatus
from app.main import app
from app.monitoring.checks import check_http
from app.security.rate_limit import InMemoryRateLimiter

# ---------------------------------------------------------------------------
# A3-SSRF-1 (FIXED): check_http now follows redirects manually
# (follow_redirects=False on each individual request) and re-validates
# EVERY redirect destination through validate_outbound_url before ever
# requesting it — see app.monitoring.checks's own _MAX_REDIRECTS/
# _is_redirect. A public URL that redirects to a private/internal address
# is never followed; a normal, legitimate public-to-public redirect
# (bare domain -> www, http -> https) still works.
# ---------------------------------------------------------------------------


def test_a3_ssrf_1_redirect_to_a_private_address_is_never_followed(monkeypatch: pytest.MonkeyPatch):
    requested_urls: list[str] = []

    class _RedirectResponse:
        status_code = 302
        headers = {"location": "http://169.254.169.254/latest/meta-data/"}
        text = ""

    def _fake_get(url, **kwargs):
        requested_urls.append(url)
        return _RedirectResponse()

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fake_get)

    result = check_http("https://example.com")

    assert result.status == HealthStatus.DOWN
    # The private destination is validated and rejected — never actually
    # requested. Exactly one real HTTP call happened (the first, public
    # one); the redirect target never became a second `httpx.get`.
    assert requested_urls == ["https://example.com"]


def test_a3_ssrf_1_normal_public_redirect_is_still_followed(monkeypatch: pytest.MonkeyPatch):
    """The fix re-validates each hop — it does not simply refuse every
    redirect, which would misreport plenty of genuinely healthy real
    business websites (a bare-domain -> www or http -> https redirect is
    extremely common) as down."""
    requested_urls: list[str] = []

    class _RedirectResponse:
        status_code = 301
        headers = {"location": "https://www.example.com/"}
        text = ""

    class _FinalResponse:
        status_code = 200
        headers: dict = {}
        text = "<html><form></form></html>"

    def _fake_get(url, **kwargs):
        requested_urls.append(url)
        return _RedirectResponse() if url == "https://example.com" else _FinalResponse()

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fake_get)

    result = check_http("https://example.com")

    assert result.status == HealthStatus.HEALTHY
    assert requested_urls == ["https://example.com", "https://www.example.com/"]


# ---------------------------------------------------------------------------
# A3-UPLOAD-1 (FIXED): image/svg+xml is no longer in
# _ALLOWED_UPLOAD_CONTENT_TYPES at all, and LOGO/IMAGE uploads are now
# validated against their real bytes (app.storage.image_validation), never
# the client-declared Content-Type header — see
# app.routers.creative._validate_uploaded_content. Comprehensive coverage
# for the fix (valid JPEG/PNG/WebP, fake-MIME rejection, mismatched-header
# acceptance, replace/batch parity) lives in tests/test_asset_upload_api.py;
# this test is the direct regression pin for the exact payload the
# original finding used.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(session, tmp_path, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path / "uploads"))
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def test_a3_upload_1_svg_with_embedded_script_is_rejected(
    client: TestClient, session, tenant: Tenant, business, tmp_path
):
    malicious_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(document.domain)">'
        b"<script>alert(document.domain)</script></svg>"
    )

    response = client.post(
        f"/businesses/{business.id}/assets/upload",
        headers={"X-Tenant-Id": str(tenant.id)},
        files={"file": ("logo.svg", io.BytesIO(malicious_svg), "image/svg+xml")},
        data={"kind": "logo"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "invalid_image_content"

    # Nothing was ever written to storage.
    uploads_dir = tmp_path / "uploads"
    assert not uploads_dir.exists() or not any(uploads_dir.rglob("*"))
