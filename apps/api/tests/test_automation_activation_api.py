"""POST /businesses/{id}/automation/activate, .../deactivate, and
GET .../automation (app.routers.businesses): the HTTP boundary around
activate/deactivate_lead_capture_automation and get_automation_state —
missing n8n configuration, unsupported capability configuration,
automation not enabled, engine failure, repeated activation not
duplicating, deactivate/reactivate, reload returning persisted state,
tenant isolation, and that the n8n API key never appears in any
response body.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.automation.n8n import N8nClient
from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_n8n_client, get_session
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
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
def _n8n_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "n8n_base_url", "https://n8n.example.com")
    monkeypatch.setattr(settings, "n8n_api_key", API_KEY)


@pytest.fixture(autouse=True)
def _clear_n8n_client_override():
    yield
    app.dependency_overrides.pop(get_n8n_client, None)


def _mock_n8n(handler) -> None:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://n8n.example.com")
    client = N8nClient("https://n8n.example.com", API_KEY, http_client=http_client)
    app.dependency_overrides[get_n8n_client] = lambda: client


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


def _activate(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/automation/activate", headers={"X-Tenant-Id": str(tenant_id)})


def _deactivate(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/automation/deactivate", headers={"X-Tenant-Id": str(tenant_id)})


def _get_automation(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.get(f"/businesses/{business_id}/automation", headers={"X-Tenant-Id": str(tenant_id)})


def test_activation_success_returns_a_provider_neutral_result(client: TestClient, tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, tenant.id)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["remote_id"] == "42"
    assert body["active"] is True
    assert set(body["required_capabilities"]) == {
        "lead.store",
        "lead.lookup",
        "lead.follow_up_email",
        "notification.send",
        "email.send",
        "wait",
    }
    assert API_KEY not in response.text


def test_missing_n8n_config_is_rejected(client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch):
    # No override registered — exercises the real get_n8n_client wiring.
    monkeypatch.setattr(settings, "n8n_base_url", None)
    monkeypatch.setattr(settings, "n8n_api_key", None)
    business = _create_business(client, tenant.id)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "n8n_not_configured"


def test_automation_not_enabled_is_rejected(client: TestClient, tenant: Tenant):
    disabled_config = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_copy(deep=True)
    disabled_config.automation.lead_capture = False
    business = _create_business(client, tenant.id, config=disabled_config.model_dump(mode="json"))

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "automation_not_enabled"


def test_business_without_config_is_rejected(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id, config=None)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_business_config"


def test_n8n_failure_is_reported_as_a_failure_never_as_active(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "automation_activation_failed"


def test_activation_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, other_tenant.id)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_activation_requires_a_tenant_header(client: TestClient, tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, tenant.id)

    response = client.post(f"/businesses/{business['id']}/automation/activate")

    assert response.status_code == 422


def test_repeated_activation_does_not_duplicate(client: TestClient, tenant: Tenant):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _successful_n8n_handler(request)

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)

    first = _activate(client, business["id"], tenant.id)
    second = _activate(client, business["id"], tenant.id)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["remote_id"] == first.json()["remote_id"]
    assert len(calls) == 2  # create + activate, exactly once — the second POST never touched n8n


def test_get_automation_returns_null_before_any_activation(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = _get_automation(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    assert response.json() is None


def test_get_automation_reflects_persisted_state_after_reload(client: TestClient, tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, tenant.id)
    activated = _activate(client, business["id"], tenant.id)

    reloaded = _get_automation(client, business["id"], tenant.id)

    assert reloaded.status_code == 200, reloaded.text
    body = reloaded.json()
    assert body["remote_id"] == activated.json()["remote_id"]
    assert body["status"] == "active"
    assert body["active"] is True


def test_deactivate_success_flips_status_to_inactive(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    _activate(client, business["id"], tenant.id)

    response = _deactivate(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "inactive"
    assert body["active"] is False
    assert API_KEY not in response.text


def test_deactivate_remote_failure_keeps_local_state_unchanged(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(500, text="internal server error")
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    _activate(client, business["id"], tenant.id)

    response = _deactivate(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "automation_deactivation_failed"

    state = _get_automation(client, business["id"], tenant.id)
    assert state.json()["status"] == "active"


def test_deactivate_without_prior_activation_is_rejected(client: TestClient, tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, tenant.id)

    response = _deactivate(client, business["id"], tenant.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "automation_not_activated"


def test_deactivate_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, other_tenant.id)
    _activate(client, business["id"], other_tenant.id)

    response = _deactivate(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_get_automation_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_n8n(_successful_n8n_handler)
    business = _create_business(client, other_tenant.id)
    _activate(client, business["id"], other_tenant.id)

    response = _get_automation(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_reactivate_after_deactivate(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        if request.method == "PUT":
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        if request.url.path.endswith("/deactivate"):
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    _mock_n8n(handler)
    business = _create_business(client, tenant.id)
    _activate(client, business["id"], tenant.id)
    _deactivate(client, business["id"], tenant.id)

    response = _activate(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active"
    assert body["remote_id"] == "42"
