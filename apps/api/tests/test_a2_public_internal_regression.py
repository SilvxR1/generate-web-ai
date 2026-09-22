"""A2 explicitly must not touch two existing trust boundaries:
/public/businesses/{id}/* (and /health) stay intentionally unauthenticated,
and /internal/* stays gated by X-Internal-Automation-Token alone, never a
session. Neither router depends on get_current_tenant_id/get_current_session
at all (see app.routers.public's own module docstring and
app.routers.internal_automation's router-level
Depends(verify_internal_automation_token)) — this file makes that
structural fact an explicit, visible regression test rather than only an
inference from the rest of the suite passing."""

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    app.dependency_overrides[get_optional_notification_sender] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
        app.dependency_overrides.pop(get_optional_notification_sender, None)


def test_health_needs_no_authentication(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200


def test_public_lead_capture_needs_no_authentication(client: TestClient, business):
    response = client.post(
        f"/public/businesses/{business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Presupuesto, por favor.",
            "consent": True,
        },
    )
    assert response.status_code == 201
    # No X-Tenant-Id was ever sent — tenant_id is derived purely from the
    # path's business_id, exactly as before A2 (see app.routers.public's
    # own docstring: this endpoint has no X-Tenant-Id concept at all).


def test_public_analytics_event_needs_no_authentication(client: TestClient, business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "page_view", "source_page": "/"},
    )
    assert response.status_code == 201


def test_public_lead_capture_ignores_a_session_cookie_if_present(client: TestClient, business):
    """Even a caller that happens to be carrying an unrelated session
    cookie must not have it change this endpoint's behavior — it has no
    session concept to begin with."""
    client.cookies.set("gwa_session", "irrelevant-garbage-value")

    response = client.post(
        f"/public/businesses/{business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Presupuesto, por favor.",
            "consent": True,
        },
    )
    assert response.status_code == 201


def test_internal_route_rejects_missing_token(client: TestClient):
    response = client.post(
        "/internal/leads",
        json={
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "business_id": "00000000-0000-0000-0000-000000000000",
            "source": "website_form",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


def test_internal_route_accepts_token_alone_no_session_needed(client: TestClient, tenant, business, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "internal_automation_token", "test-internal-token")

    response = client.post(
        "/internal/leads",
        json={
            "tenant_id": str(tenant.id),
            "business_id": str(business.id),
            "source": "website_form",
        },
        headers={"X-Internal-Automation-Token": "test-internal-token"},
    )
    assert response.status_code == 201
    # No X-Tenant-Id header, no session cookie — the internal boundary is
    # (and must remain) entirely separate from A2's session/TenantAccess
    # machinery, exactly as before.


def test_internal_route_rejects_wrong_token(client: TestClient, tenant, business, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "internal_automation_token", "test-internal-token")

    response = client.post(
        "/internal/leads",
        json={"tenant_id": str(tenant.id), "business_id": str(business.id), "source": "website_form"},
        headers={"X-Internal-Automation-Token": "wrong-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"
