"""GET /businesses/{id}/metrics (app.routers.analytics, P1.8): "no data
yet" (None) before any analytics event has ever been recorded, real
counts once they have, form_leads always a known count from the
authoritative Lead table, conversion rate, window selection, and tenant
isolation."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models.analytics_event import AnalyticsEvent
from app.db.models.business import Business
from app.db.models.lead import Lead
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


def _headers(tenant_id) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def _add_event(session, *, tenant_id, business_id, event_type, occurred_at) -> AnalyticsEvent:
    event = AnalyticsEvent(
        tenant_id=tenant_id, business_id=business_id, event_type=event_type, occurred_at=occurred_at
    )
    session.add(event)
    session.flush()
    return event


def _add_lead(session, *, tenant_id, business_id, created_at) -> Lead:
    lead = Lead(tenant_id=tenant_id, business_id=business_id, source="website_form", created_at=created_at)
    session.add(lead)
    session.flush()
    return lead


def test_metrics_show_no_data_yet_before_any_analytics_event(client: TestClient, tenant: Tenant, business: Business):
    response = client.get(f"/businesses/{business.id}/metrics", headers=_headers(tenant.id))

    assert response.status_code == 200
    body = response.json()
    assert body["website_visits"] is None
    assert body["whatsapp_clicks"] is None
    assert body["phone_clicks"] is None
    assert body["email_clicks"] is None
    # form_leads is always a known count, never "no data yet".
    assert body["form_leads"] == 0
    assert body["lead_conversion_rate"] is None


def test_metrics_compute_real_counts_once_events_exist(
    client: TestClient, session, tenant: Tenant, business: Business
):
    now = datetime.now(UTC)
    kwargs = {"session": session, "tenant_id": tenant.id, "business_id": business.id}
    _add_event(**kwargs, event_type="page_view", occurred_at=now)
    _add_event(**kwargs, event_type="page_view", occurred_at=now)
    _add_event(**kwargs, event_type="whatsapp_click", occurred_at=now)
    _add_lead(session, tenant_id=tenant.id, business_id=business.id, created_at=now)

    response = client.get(f"/businesses/{business.id}/metrics", headers=_headers(tenant.id))

    body = response.json()
    assert body["website_visits"] == 2
    assert body["whatsapp_clicks"] == 1
    assert body["phone_clicks"] == 0
    assert body["email_clicks"] == 0
    assert body["form_leads"] == 1
    assert body["lead_conversion_rate"] == pytest.approx(0.5)


def test_metrics_exclude_events_outside_the_window(client: TestClient, session, tenant: Tenant, business: Business):
    now = datetime.now(UTC)
    old = now - timedelta(days=40)
    _add_event(session, tenant_id=tenant.id, business_id=business.id, event_type="page_view", occurred_at=old)

    response = client.get(f"/businesses/{business.id}/metrics", params={"window": "30d"}, headers=_headers(tenant.id))

    body = response.json()
    # An event exists at all, so this is a known 0, not "no data yet".
    assert body["website_visits"] == 0


def test_metrics_window_selection(client: TestClient, session, tenant: Tenant, business: Business):
    now = datetime.now(UTC)
    within_7d = now - timedelta(days=3)
    within_30d_not_7d = now - timedelta(days=20)
    kwargs = {"session": session, "tenant_id": tenant.id, "business_id": business.id, "event_type": "page_view"}
    _add_event(**kwargs, occurred_at=within_7d)
    _add_event(**kwargs, occurred_at=within_30d_not_7d)

    seven_day = client.get(f"/businesses/{business.id}/metrics", params={"window": "7d"}, headers=_headers(tenant.id))
    thirty_day = client.get(
        f"/businesses/{business.id}/metrics", params={"window": "30d"}, headers=_headers(tenant.id)
    )

    assert seven_day.json()["website_visits"] == 1
    assert thirty_day.json()["website_visits"] == 2


def test_metrics_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    import uuid

    response = client.get(f"/businesses/{uuid.uuid4()}/metrics", headers=_headers(tenant.id))

    assert response.status_code == 404


def test_metrics_never_leak_across_tenants(
    client: TestClient, session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    _add_event(
        session, tenant_id=tenant.id, business_id=business.id, event_type="page_view", occurred_at=datetime.now(UTC)
    )

    response = client.get(f"/businesses/{business.id}/metrics", headers=_headers(other_tenant.id))

    assert response.status_code == 404
