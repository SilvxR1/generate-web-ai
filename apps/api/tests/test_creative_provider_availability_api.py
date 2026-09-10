"""GET /businesses/{id}/creative-providers (app.routers.creative): honest
provider availability. Phase 13: 'Internal ✓ Available, Higgsfield Not
configured' is the expected default state — no Higgsfield credentials
configured anywhere in this test run."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.main import app


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_internal_is_always_available_and_higgsfield_is_not_by_default(
    client: TestClient, tenant: Tenant, business
):
    response = client.get(f"/businesses/{business.id}/creative-providers", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    by_provider = {row["provider"]: row for row in response.json()}

    assert by_provider["internal"]["available"] is True
    assert by_provider["internal"]["unavailable_reason"] is None
    assert set(by_provider["internal"]["capabilities"]) == {"website", "website_concept"}

    assert by_provider["higgsfield"]["available"] is False
    assert by_provider["higgsfield"]["unavailable_reason"] == "Higgsfield is not configured on this server."
    # Capabilities are still reported for the unavailable provider — what
    # it *would* support once configured, not an empty placeholder.
    assert set(by_provider["higgsfield"]["capabilities"]) == {
        "website",
        "website_concept",
        "image",
        "video",
        "visual_asset",
    }


def test_higgsfield_shows_available_once_configured(
    client: TestClient, tenant: Tenant, business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "higgsfield_api_key", "test-key")
    monkeypatch.setattr(settings, "higgsfield_base_url", "https://higgsfield.example.invalid")

    response = client.get(f"/businesses/{business.id}/creative-providers", headers={"X-Tenant-Id": str(tenant.id)})

    by_provider = {row["provider"]: row for row in response.json()}
    assert by_provider["higgsfield"]["available"] is True
    assert by_provider["higgsfield"]["unavailable_reason"] is None
