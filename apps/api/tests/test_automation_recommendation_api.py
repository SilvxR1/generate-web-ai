"""GET /businesses/automation-recommendation (app.routers.businesses):
Studio's read-only window into
app.domain.workflow_config.vertical_templates — a pure, stateless
lookup by vertical, never a second persisted config."""

import pytest
from fastapi.testclient import TestClient

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


def _get_recommendation(client: TestClient, vertical: str, tenant: Tenant):
    return client.get(
        "/businesses/automation-recommendation",
        params={"vertical": vertical},
        headers={"X-Tenant-Id": str(tenant.id)},
    )


def test_home_renovation_recommendation(client: TestClient, tenant: Tenant):
    response = _get_recommendation(client, "home_renovation", tenant)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "lead_notifications": True,
        "customer_acknowledgement": True,
        "follow_up_enabled": True,
        "follow_up_delay_hours": 24,
    }


def test_restaurant_recommendation(client: TestClient, tenant: Tenant):
    response = _get_recommendation(client, "restaurant", tenant)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "lead_notifications": True,
        "customer_acknowledgement": True,
        "follow_up_enabled": False,
        "follow_up_delay_hours": 24,
    }


def test_b2b_services_recommendation(client: TestClient, tenant: Tenant):
    response = _get_recommendation(client, "b2b_services", tenant)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "lead_notifications": True,
        "customer_acknowledgement": True,
        "follow_up_enabled": True,
        "follow_up_delay_hours": 48,
    }


def test_unmapped_vertical_gets_the_generic_fallback(client: TestClient, tenant: Tenant):
    response = _get_recommendation(client, "hotel", tenant)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "lead_notifications": True,
        "customer_acknowledgement": False,
        "follow_up_enabled": False,
        "follow_up_delay_hours": 24,
    }


def test_requires_a_tenant_header(client: TestClient):
    response = client.get("/businesses/automation-recommendation", params={"vertical": "restaurant"})

    assert response.status_code == 422


def test_rejects_an_unknown_vertical_value(client: TestClient, tenant: Tenant):
    response = _get_recommendation(client, "not-a-real-vertical", tenant)

    assert response.status_code == 422
