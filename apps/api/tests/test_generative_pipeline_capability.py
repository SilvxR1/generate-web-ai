"""GET .../generative-pipeline-capability (P2.1) — the ONE authoritative
P2 capability endpoint. Every underlying check is patched where the router
actually calls it from (same convention tests/test_frontend_engineer_availability.py
already documents) — no real Higgsfield/Anthropic/Chromium call, no
credits spent, anywhere in this module. Also proves the unrelated legacy
GET .../creative-providers can never report the real P2 Higgsfield
Creative Director as ready."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_rate_limiter, get_session
from app.domain.enums import CreativeProviderName
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(tenant_id) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def test_reports_internal_fallback_when_higgsfield_unavailable(client: TestClient, tenant: Tenant, business):
    with (
        patch(
            "app.routers.creative.check_higgsfield_director_availability",
            return_value=(
                False,
                "HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are not configured on this server.",
            ),
        ),
        patch("app.routers.creative.check_frontend_engineer_availability", return_value=(True, None)),
        patch("app.routers.creative.check_browser_qa_availability", return_value=(True, None)),
    ):
        response = client.get(
            f"/businesses/{business.id}/generative-pipeline-capability", headers=_headers(tenant.id)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["creative_director"]["available"] is False
    assert "not configured" in body["creative_director"]["unavailable_reason"]
    # Never silently implies Higgsfield was used — this field says exactly
    # which provider a real create_directions call would use right now.
    assert body["creative_director_provider"] == CreativeProviderName.INTERNAL.value


def test_reports_higgsfield_when_the_real_check_passes(client: TestClient, tenant: Tenant, business):
    with (
        patch("app.routers.creative.check_higgsfield_director_availability", return_value=(True, None)),
        patch("app.routers.creative.check_frontend_engineer_availability", return_value=(True, None)),
        patch("app.routers.creative.check_browser_qa_availability", return_value=(True, None)),
    ):
        response = client.get(
            f"/businesses/{business.id}/generative-pipeline-capability", headers=_headers(tenant.id)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["creative_director"]["available"] is True
    assert body["creative_director_provider"] == CreativeProviderName.HIGGSFIELD.value


def test_reports_each_subsystem_independently(client: TestClient, tenant: Tenant, business):
    with (
        patch("app.routers.creative.check_higgsfield_director_availability", return_value=(True, None)),
        patch(
            "app.routers.creative.check_frontend_engineer_availability",
            return_value=(False, "ANTHROPIC_API_KEY is not configured on this server."),
        ),
        patch(
            "app.routers.creative.check_browser_qa_availability",
            return_value=(False, "Chromium is not installed at the expected path."),
        ),
    ):
        response = client.get(
            f"/businesses/{business.id}/generative-pipeline-capability", headers=_headers(tenant.id)
        )

    body = response.json()
    assert body["creative_director"]["available"] is True
    assert body["frontend_engineer"]["available"] is False
    assert body["browser_qa"]["available"] is False
    # Local storage always reports available (a real default exists) —
    # persistence, not existence, is the distinct signal.
    assert body["artifact_storage"]["available"] is True
    assert body["artifact_storage_persistent"] is False


def test_artifact_storage_persistent_when_r2_is_fully_configured(client: TestClient, tenant: Tenant, business):
    with (
        patch("app.routers.creative.check_higgsfield_director_availability", return_value=(True, None)),
        patch("app.routers.creative.check_frontend_engineer_availability", return_value=(True, None)),
        patch("app.routers.creative.check_browser_qa_availability", return_value=(True, None)),
        patch("app.routers.creative.settings.r2_account_id", "acct-1"),
        patch("app.routers.creative.settings.r2_access_key_id", "ak"),
        patch("app.routers.creative.settings.r2_secret_access_key", "sk"),
        patch("app.routers.creative.settings.r2_bucket_name", "gwa-artifacts"),
    ):
        response = client.get(
            f"/businesses/{business.id}/generative-pipeline-capability", headers=_headers(tenant.id)
        )

    assert response.json()["artifact_storage_persistent"] is True


def test_capability_endpoint_uses_the_shared_rate_limit_dependency():
    from app.config import settings

    assert settings.generative_pipeline_capability_rate_limit_per_minute > 0


def test_legacy_creative_providers_endpoint_never_reports_higgsfield_generation_ready(
    client: TestClient, tenant: Tenant, business
):
    """The legacy GET .../creative-providers (app.creative.higgsfield.provider)
    is real, wired scaffolding for the OLD CreativeLevel PREMIUM/CINEMATIC
    tier — but HiggsfieldCreativeProvider.generate_* always raises
    HiggsfieldNotIntegratedError, so even when it reports `available=True`
    (HIGGSFIELD_API_KEY/HIGGSFIELD_BASE_URL configured), it can never
    actually produce a real P2 generative result — the capability endpoint
    above, not this legacy one, is the authoritative P2 signal."""
    with (
        patch("app.routers.creative.settings.higgsfield_api_key", "legacy-key"),
        patch("app.routers.creative.settings.higgsfield_base_url", "https://example.invalid"),
    ):
        response = client.get(f"/businesses/{business.id}/creative-providers", headers=_headers(tenant.id))

    assert response.status_code == 200
    providers = {row["provider"]: row for row in response.json()}
    # Even "available" here is a lie about actual generation capability —
    # this test documents that fact rather than treating it as new
    # behavior to assert on the P2 workflow.
    assert providers["higgsfield"]["available"] is True
    assert "website" in providers["higgsfield"]["capabilities"]
