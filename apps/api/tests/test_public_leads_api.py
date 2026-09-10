"""POST /public/businesses/{id}/leads (app.routers.public) — Phase 7/8/9:
the anonymous lead-capture endpoint that works without n8n. Covers
tenant derivation (never accepted from the caller), spam boundary,
lead-persisted-before-notification, and notification failure never
losing the lead."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session
from app.main import app
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    # A fresh limiter per test — this module's own module-level
    # `_rate_limiter` singleton (app.dependencies) would otherwise carry
    # request counts across every test in this file, since they all POST
    # to the same rate-limited endpoint (the exact failure this override
    # fixes: a later test getting 429 instead of the status its own
    # assertions expect).
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _payload(**overrides: object) -> dict:
    payload = {
        "name": "Maria Garcia",
        "email": "maria@example.com",
        "message": "Necesito un presupuesto para mi cocina.",
        "consent": True,
        "rendered_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_public_lead_is_created_and_never_needs_a_tenant_header(client: TestClient, business):
    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201, response.text
    assert response.json() == {"received": True}


def test_public_lead_for_unknown_business_is_404(client: TestClient):
    response = client.post(f"/public/businesses/{uuid.uuid4()}/leads", json=_payload())

    assert response.status_code == 404


def test_public_lead_requires_at_least_email_or_phone(client: TestClient, business):
    response = client.post(
        f"/public/businesses/{business.id}/leads", json=_payload(email=None)
    )

    assert response.status_code == 422


def test_public_lead_persists_with_tenant_derived_from_the_business_not_the_caller(
    client: TestClient, business, session
):
    from app.repositories.lead import LeadRepository

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())
    assert response.status_code == 201

    leads = LeadRepository(session).list_for_business(business.tenant_id, business.id)
    assert len(leads) == 1
    assert leads[0].tenant_id == business.tenant_id
    assert leads[0].consent_given is True
    assert leads[0].source == "website_form"


def test_honeypot_field_silently_drops_the_submission(client: TestClient, business, session):
    from app.repositories.lead import LeadRepository

    response = client.post(
        f"/public/businesses/{business.id}/leads",
        json=_payload(company_website="I am a bot"),
    )

    # Same response shape as a real success — never a signal a bot can
    # learn from (Phase 8).
    assert response.status_code == 201
    assert response.json() == {"received": True}
    assert LeadRepository(session).list_for_business(business.tenant_id, business.id) == []


def test_submission_faster_than_a_human_could_type_is_silently_dropped(client: TestClient, business, session):
    from app.repositories.lead import LeadRepository

    response = client.post(
        f"/public/businesses/{business.id}/leads",
        json=_payload(rendered_at=datetime.now(UTC).isoformat()),
    )

    assert response.status_code == 201
    assert LeadRepository(session).list_for_business(business.tenant_id, business.id) == []


def test_a_real_slow_submission_with_no_honeypot_is_not_spam(client: TestClient, business, session):
    from app.repositories.lead import LeadRepository

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201
    assert len(LeadRepository(session).list_for_business(business.tenant_id, business.id)) == 1


class _FailingSender(NotificationSender):
    def send(self, message: NotificationEmail) -> None:
        raise NotificationSenderError("simulated provider outage")


def test_notification_failure_never_loses_the_lead(client: TestClient, business, session):
    from app.repositories.lead import LeadRepository

    app.dependency_overrides[get_optional_notification_sender] = lambda: _FailingSender()
    try:
        response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)

    # The request still succeeds from the caller's point of view, and the
    # lead is there regardless of the notification provider failing.
    assert response.status_code == 201
    assert len(LeadRepository(session).list_for_business(business.tenant_id, business.id)) == 1


def test_public_lead_never_leaks_into_another_tenants_business_list(
    client: TestClient, business, other_tenant: Tenant
):
    client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    response = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(other_tenant.id)})

    assert response.status_code == 404


def test_owning_tenant_can_see_the_public_lead_in_studio(client: TestClient, business, tenant: Tenant):
    client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    response = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["source"] == "website_form"


def test_rejects_when_business_has_explicitly_disabled_lead_capture(client: TestClient, session, tenant, business):
    business.config = {
        "schema_version": 1,
        "business_profile": {"name": business.name, "slug": business.slug, "industry": "other"},
        "lead_management": {"enabled": False},
    }
    session.flush()

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "lead_capture_disabled"
