"""DELETE /businesses/{id} (app.routers.businesses): tenant isolation,
not-found, cascade cleanup of every row that hangs off a Business
(website, workflow, leads, internal notifications, integrations and
their credentials), and the one thing cascade delete can't do on its
own — deactivating a currently-*active* remote n8n automation before
the local Workflow row disappears, so a deleted business never leaves
an active automation silently running with no local record of it.

See delete_business's own docstring (app.routers.businesses) for the
documented, deliberate scope limits this file also exercises: no
`delete_workflow` capability exists on N8nClient/N8nAutomationEngine
yet (deactivate only, never delete-remote), and no delete/unpublish
capability exists on CloudflarePagesClient/CloudflarePagesPublisher
either — both are left as-is, documented as deferred cleanup.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.automation.n8n import N8nClient
from app.config import settings
from app.db.models.business import Business
from app.db.models.credential import Credential
from app.db.models.integration import Integration
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.db.models.workflow import Workflow
from app.dependencies import get_n8n_client, get_optional_n8n_client, get_session
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.enums import (
    BusinessStatus,
    BusinessVertical,
    IntegrationProvider,
    IntegrationStatus,
    LeadStatus,
    WebsiteStatus,
    WorkflowStatus,
)
from app.main import app

API_KEY = "n8n-super-secret-api-key"


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _clear_n8n_client_override():
    yield
    app.dependency_overrides.pop(get_n8n_client, None)
    app.dependency_overrides.pop(get_optional_n8n_client, None)


def _mock_n8n(handler) -> None:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://n8n.example.com")
    n8n_client = N8nClient("https://n8n.example.com", API_KEY, http_client=http_client)
    # DELETE /businesses/{id} depends on get_optional_n8n_client (never
    # hard-requires n8n), not get_n8n_client — both need overriding so
    # the mocked transport is used by whichever dependency a given route
    # actually declares. See get_optional_n8n_client's own docstring.
    app.dependency_overrides[get_n8n_client] = lambda: n8n_client
    app.dependency_overrides[get_optional_n8n_client] = lambda: n8n_client


def _successful_n8n_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/workflows":
        return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
    return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})


def _create_business(client: TestClient, tenant_id: uuid.UUID, **overrides: object) -> dict:
    payload = {
        "name": "Reforma Casa Valencia",
        "slug": "reforma-casa-valencia",
        "vertical": "home_renovation",
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": "draft",
        "config": EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json"),
    }
    payload.update(overrides)
    response = client.post("/businesses", json=payload, headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def _delete(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.delete(f"/businesses/{business_id}", headers={"X-Tenant-Id": str(tenant_id)})


def _activate(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/automation/activate", headers={"X-Tenant-Id": str(tenant_id)})


def _deactivate(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/automation/deactivate", headers={"X-Tenant-Id": str(tenant_id)})


def _make_business_row(
    session, tenant_id: uuid.UUID, *, name: str = "Sacri Barber", slug: str = "sacri-barber"
) -> Business:
    business = Business(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        vertical=BusinessVertical.OTHER,
        raw_description="Barberia clasica en el centro de la ciudad con mas de cinco anos de trayectoria.",
        status=BusinessStatus.DRAFT,
    )
    session.add(business)
    session.flush()
    return business


# --- Not found -------------------------------------------------------------


def test_delete_missing_business_returns_not_found(client: TestClient, tenant: Tenant):
    response = _delete(client, str(uuid.uuid4()), tenant.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "business_not_found"


def test_delete_requires_a_tenant_header(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = client.delete(f"/businesses/{business['id']}")

    assert response.status_code == 422


# --- Tenant isolation --------------------------------------------------


def test_delete_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, other_tenant.id)

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 404
    still_there = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert still_there.status_code == 200


# --- Basic success + cascade cleanup ------------------------------------


def test_delete_success_returns_204_and_the_business_is_gone(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 204
    assert response.content == b""
    gone = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert gone.status_code == 404


def test_delete_cascades_to_every_business_owned_row(client: TestClient, session, tenant: Tenant):
    business_row = _make_business_row(session, tenant.id)
    business_id = business_row.id

    website = Website(
        tenant_id=tenant.id, business_id=business_id, status=WebsiteStatus.LIVE, deploy_url="https://x.example/"
    )
    session.add(website)

    workflow = Workflow(
        tenant_id=tenant.id,
        business_id=business_id,
        name="Sacri Barber — Lead capture",
        status=WorkflowStatus.INACTIVE,
        local_workflow_id="sacri-barber-lead-capture",
        required_capabilities=["lead.store"],
    )
    session.add(workflow)

    lead = Lead(
        tenant_id=tenant.id, business_id=business_id, source="website_form", name="Juan Perez", status=LeadStatus.NEW
    )
    session.add(lead)

    integration = Integration(
        tenant_id=tenant.id,
        business_id=business_id,
        provider=IntegrationProvider.WEBHOOK,
        status=IntegrationStatus.CONNECTED,
    )
    session.add(integration)
    session.flush()

    credential = Credential(
        tenant_id=tenant.id, integration_id=integration.id, encrypted_value="gAAAAA-fake-fernet-token"
    )
    session.add(credential)
    session.flush()

    notification = InternalNotification(
        tenant_id=tenant.id,
        business_id=business_id,
        source="lead.submitted",
        summary="New lead captured",
        channel="internal",
    )
    session.add(notification)
    session.flush()

    website_id, workflow_id, lead_id, integration_id, credential_id, notification_id = (
        website.id,
        workflow.id,
        lead.id,
        integration.id,
        credential.id,
        notification.id,
    )

    response = _delete(client, str(business_id), tenant.id)

    assert response.status_code == 204
    assert session.get(Business, business_id) is None
    assert session.get(Website, website_id) is None
    assert session.get(Workflow, workflow_id) is None
    assert session.get(Lead, lead_id) is None
    assert session.get(Integration, integration_id) is None
    assert session.get(Credential, credential_id) is None
    assert session.get(InternalNotification, notification_id) is None


def test_delete_of_one_business_does_not_touch_another_tenants_rows(
    client: TestClient, session, tenant: Tenant, other_tenant: Tenant
):
    doomed = _make_business_row(session, tenant.id, name="Sacri Barber", slug="sacri-barber")
    survivor = _make_business_row(session, other_tenant.id, name="Reforma Pepe", slug="reforma-pepe")
    survivor_lead = Lead(
        tenant_id=other_tenant.id, business_id=survivor.id, source="website_form", name="Ana", status=LeadStatus.NEW
    )
    session.add(survivor_lead)
    session.flush()
    survivor_id, survivor_lead_id = survivor.id, survivor_lead.id

    response = _delete(client, str(doomed.id), tenant.id)

    assert response.status_code == 204
    assert session.get(Business, survivor_id) is not None
    assert session.get(Lead, survivor_lead_id) is not None


# --- Active remote automation must be deactivated first --------------------


def test_delete_deactivates_active_automation_before_deleting(client: TestClient, tenant: Tenant):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    activated = _activate(client, business["id"], tenant.id)
    assert activated.status_code == 200, activated.text
    calls.clear()

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 204
    assert any(path.endswith("/deactivate") for path in calls)
    gone = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert gone.status_code == 404


def test_delete_fails_and_keeps_the_business_when_n8n_is_not_configured_but_automation_is_active(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, tenant.id)
    activated = _activate(client, business["id"], tenant.id)
    assert activated.status_code == 200, activated.text

    # Simulate n8n no longer being configured on this server, and stop
    # overriding get_optional_n8n_client so the real (now-unconfigured)
    # wiring applies.
    monkeypatch.setattr(settings, "n8n_base_url", None)
    monkeypatch.setattr(settings, "n8n_api_key", None)
    app.dependency_overrides.pop(get_optional_n8n_client, None)

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "n8n_not_configured"
    still_there = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert still_there.status_code == 200


def test_delete_fails_and_keeps_the_business_when_remote_deactivation_fails(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    activated = _activate(client, business["id"], tenant.id)
    assert activated.status_code == 200, activated.text

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "automation_deactivation_failed"
    still_there = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert still_there.status_code == 200


def test_delete_succeeds_without_n8n_configured_when_automation_was_never_activated(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "n8n_base_url", None)
    monkeypatch.setattr(settings, "n8n_api_key", None)
    business = _create_business(client, tenant.id)

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 204
    gone = client.get(f"/businesses/{business['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert gone.status_code == 404


def test_delete_succeeds_without_calling_n8n_when_automation_was_deactivated_already(
    client: TestClient, tenant: Tenant
):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    _activate(client, business["id"], tenant.id)
    _deactivate(client, business["id"], tenant.id)
    calls.clear()

    response = _delete(client, business["id"], tenant.id)

    assert response.status_code == 204
    # Already inactive — deleting must not call n8n again at all.
    assert calls == []
