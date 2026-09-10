"""GET /businesses/{id}/operational-providers (app.routers.businesses,
P1.12): honest email/n8n availability, real-settings-backed."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.business import Business
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


def test_reports_unavailable_when_unconfigured(
    client: TestClient, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    # Explicitly unconfigured rather than relying on the ambient
    # environment having nothing set — a developer's local .env may
    # legitimately configure SMTP/n8n for their own dev workflow (see
    # the CI-fix precedent for this exact class of test-hermeticity bug:
    # apps/api/tests/test_website_draft_api.py's _DefaultFakePublisher).
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "resend_from_address", None)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from_address", None)
    monkeypatch.setattr(settings, "n8n_base_url", None)
    monkeypatch.setattr(settings, "n8n_api_key", None)

    response = client.get(f"/businesses/{business.id}/operational-providers", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    by_category = {row["category"]: row for row in response.json()}
    assert by_category["email"]["available"] is False
    assert by_category["email"]["unavailable_reason"]
    assert by_category["automation"]["provider"] == "n8n"
    assert by_category["automation"]["available"] is False
    assert by_category["automation"]["unavailable_reason"]


def test_reports_resend_available_when_configured(
    client: TestClient, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "resend_api_key", "fake-key")
    monkeypatch.setattr(settings, "resend_from_address", "no-reply@example.com")

    response = client.get(f"/businesses/{business.id}/operational-providers", headers={"X-Tenant-Id": str(tenant.id)})

    by_category = {row["category"]: row for row in response.json()}
    assert by_category["email"]["provider"] == "resend"
    assert by_category["email"]["available"] is True
    assert by_category["email"]["unavailable_reason"] is None


def test_reports_n8n_available_when_configured(
    client: TestClient, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "n8n_base_url", "https://n8n.example.com")
    monkeypatch.setattr(settings, "n8n_api_key", "fake-key")

    response = client.get(f"/businesses/{business.id}/operational-providers", headers={"X-Tenant-Id": str(tenant.id)})

    by_category = {row["category"]: row for row in response.json()}
    assert by_category["automation"]["available"] is True
    assert by_category["automation"]["unavailable_reason"] is None


def test_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    import uuid

    response = client.get(f"/businesses/{uuid.uuid4()}/operational-providers", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 404
