"""GET /businesses/{id}/workflow-preview (app.routers.businesses): the
read-only preview an onboarding UI shows before any automation is ever
activated — no n8n call, no Workflow/WorkflowVersion row written."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
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


def _business_payload(**overrides: object) -> dict:
    payload = {
        "name": "Reforma Casa Valencia",
        "slug": "reforma-casa-valencia",
        "vertical": "home_renovation",
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": "draft",
        "config": None,
    }
    payload.update(overrides)
    return payload


def _create_business(client: TestClient, tenant_id: uuid.UUID, **overrides: object) -> dict:
    response = client.post("/businesses", json=_business_payload(**overrides), headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def test_workflow_preview_for_business_with_lead_capture_enabled(client: TestClient, tenant: Tenant):
    config = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json")
    business = _create_business(client, tenant.id, config=config)

    response = client.get(f"/businesses/{business['id']}/workflow-preview", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body is not None
    assert body["name"] == "Reforma Casa Valencia — Lead capture"
    assert body["trigger"]["type"] == "lead.submitted"
    node_actions = {node["action"] for node in body["nodes"] if node["type"] == "action"}
    expected_actions = {"lead.store", "lead.lookup", "lead.follow_up_email", "notification.send", "email.send", "wait"}
    assert node_actions == expected_actions
    assert set(body["required_capabilities"]) == expected_actions


def test_workflow_preview_is_null_when_lead_capture_is_not_enabled(client: TestClient, tenant: Tenant):
    config = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_copy(deep=True)
    config.automation.lead_capture = False
    business = _create_business(client, tenant.id, config=config.model_dump(mode="json"))

    response = client.get(f"/businesses/{business['id']}/workflow-preview", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200, response.text
    assert response.json() is None


def test_workflow_preview_is_null_when_business_has_no_config(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = client.get(f"/businesses/{business['id']}/workflow-preview", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200, response.text
    assert response.json() is None


def test_workflow_preview_404s_for_unknown_business(client: TestClient, tenant: Tenant):
    response = client.get(f"/businesses/{uuid.uuid4()}/workflow-preview", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 404


def test_workflow_preview_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    config = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json")
    business = _create_business(client, other_tenant.id, config=config)

    response = client.get(f"/businesses/{business['id']}/workflow-preview", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 404
