"""POST /public/businesses/{id}/events (app.routers.public, P1.7): the
anonymous analytics-event surface — tenant derived server-side, PII
rejected, unknown business never leaks (still 201/`received: true`),
rate limited."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.analytics_event import AnalyticsEvent
from app.db.models.business import Business
from app.dependencies import get_rate_limiter, get_session
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def test_event_is_recorded_and_never_needs_a_tenant_header(client: TestClient, session, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "page_view", "source_page": "/"},
    )

    assert response.status_code == 201
    assert response.json() == {"received": True}
    events = session.query(AnalyticsEvent).filter_by(business_id=business.id).all()
    assert len(events) == 1
    assert events[0].event_type == "page_view"
    assert events[0].tenant_id == business.tenant_id


def test_whatsapp_click_event_with_placement_metadata(client: TestClient, session, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "whatsapp_click", "metadata": {"placement": "floating"}},
    )

    assert response.status_code == 201
    event = session.query(AnalyticsEvent).filter_by(business_id=business.id).one()
    assert event.event_metadata == {"placement": "floating"}


def test_unknown_business_still_returns_received_true(client: TestClient):
    response = client.post(
        f"/public/businesses/{uuid.uuid4()}/events",
        json={"event_type": "page_view"},
    )

    assert response.status_code == 201
    assert response.json() == {"received": True}


def test_rejects_unknown_event_type(client: TestClient, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "totally_made_up"},
    )

    assert response.status_code == 422


def test_rejects_metadata_containing_an_email(client: TestClient, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "whatsapp_click", "metadata": {"note": "contact me at juan@example.com"}},
    )

    assert response.status_code == 422


def test_rejects_metadata_containing_a_phone_number(client: TestClient, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "phone_click", "metadata": {"note": "call 6001234567"}},
    )

    assert response.status_code == 422


def test_rejects_metadata_with_disallowed_key(client: TestClient, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "page_view", "metadata": {"CamelCase!": "x"}},
    )

    assert response.status_code == 422


def test_rejects_too_many_metadata_keys(client: TestClient, business: Business):
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "page_view", "metadata": {f"k{i}": "v" for i in range(6)}},
    )

    assert response.status_code == 422


def test_analytics_events_never_leak_lead_fields(client: TestClient, business: Business):
    # extra="forbid" on the request schema — a caller trying to smuggle
    # name/email/phone/message fields in is rejected outright, not
    # silently dropped.
    response = client.post(
        f"/public/businesses/{business.id}/events",
        json={"event_type": "lead_submitted", "email": "juan@example.com"},
    )

    assert response.status_code == 422


def test_event_ingestion_is_rate_limited(client: TestClient, business: Business, monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "public_analytics_rate_limit_per_minute", 1)

    first = client.post(f"/public/businesses/{business.id}/events", json={"event_type": "page_view"})
    assert first.status_code == 201

    second = client.post(f"/public/businesses/{business.id}/events", json={"event_type": "page_view"})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
