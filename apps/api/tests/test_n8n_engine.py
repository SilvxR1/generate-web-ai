"""N8nClient + N8nAutomationEngine against a mocked n8n API
(httpx.MockTransport — no real n8n instance needed): create,
activate/deactivate, get/list executions, and that an n8n-side error
propagates as N8nApiError rather than being swallowed."""

import json

import httpx
import pytest

from app.automation import AutomationEngineError
from app.automation.n8n import N8nApiError, N8nAutomationEngine, N8nClient, N8nTranslationContext
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.workflow_config import generate_lead_capture_workflow

CONTEXT = N8nTranslationContext(
    internal_leads_url="http://localhost:8000/internal/leads",
    internal_notifications_url="http://localhost:8000/internal/notifications",
    # Required now: _workflow() below includes lead.lookup and
    # email.send/lead.follow_up_email nodes (the reforma-valencia
    # fixture has follow_up and customer_acknowledgement enabled), all
    # of which the translator refuses to translate without tenant/
    # business scoping.
    tenant_id="11111111-1111-1111-1111-111111111111",
    business_id="22222222-2222-2222-2222-222222222222",
)


def _engine(handler) -> N8nAutomationEngine:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://n8n.example.com")
    client = N8nClient("https://n8n.example.com", "test-api-key", http_client=http_client)
    return N8nAutomationEngine(client, CONTEXT)


def _workflow():
    return generate_lead_capture_workflow(EXAMPLE_REFORMA_VALENCIA_CONFIG)


# --- create -------------------------------------------------------------


def test_create_workflow_sends_api_key_and_translated_payload_returns_remote_workflow():
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"id": "42", "name": "Reforma Casa Valencia — Lead capture", "active": False})

    engine = _engine(handler)
    remote = engine.create_workflow(_workflow())

    request = captured["request"]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/workflows"
    assert request.headers["X-N8N-API-KEY"] == "test-api-key"
    body = json.loads(request.content)
    assert body["nodes"][0]["type"] == "n8n-nodes-base.webhook"

    assert remote.remote_id == "42"
    assert remote.active is False


# --- activate/deactivate -------------------------------------------------


def test_activate_workflow_returns_updated_remote_workflow():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows/42/activate"
        return httpx.Response(200, json={"id": "42", "name": "Lead capture", "active": True})

    engine = _engine(handler)
    remote = engine.activate_workflow("42")

    assert remote.active is True


def test_deactivate_workflow_returns_updated_remote_workflow():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows/42/deactivate"
        return httpx.Response(200, json={"id": "42", "name": "Lead capture", "active": False})

    engine = _engine(handler)
    remote = engine.deactivate_workflow("42")

    assert remote.active is False


def test_update_workflow_sends_retranslated_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/v1/workflows/42"
        return httpx.Response(200, json={"id": "42", "name": "Lead capture", "active": False})

    engine = _engine(handler)
    remote = engine.update_workflow("42", _workflow())

    assert remote.remote_id == "42"


# --- executions -----------------------------------------------------------


def test_get_execution_maps_success_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "ex-1",
                "workflowId": "42",
                "status": "success",
                "startedAt": "2026-01-01T10:00:00.000Z",
                "stoppedAt": "2026-01-01T10:00:05.000Z",
            },
        )

    engine = _engine(handler)
    execution = engine.get_execution("ex-1")

    assert execution.status.value == "success"
    assert execution.error_summary is None
    assert execution.started_at is not None


def test_get_execution_maps_error_status_and_extracts_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "ex-2",
                "workflowId": "42",
                "status": "error",
                "data": {"resultData": {"error": {"message": "SMTP connection refused"}}},
            },
        )

    engine = _engine(handler)
    execution = engine.get_execution("ex-2")

    assert execution.status.value == "failed"
    assert execution.error_summary == "SMTP connection refused"


def test_list_executions_maps_every_item():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["workflowId"] == "42"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "ex-1", "workflowId": "42", "status": "success"},
                    {"id": "ex-2", "workflowId": "42", "status": "running"},
                ]
            },
        )

    engine = _engine(handler)
    executions = engine.list_executions("42")

    assert [e.remote_id for e in executions] == ["ex-1", "ex-2"]
    assert [e.status.value for e in executions] == ["success", "running"]


# --- n8n error propagated cleanly -------------------------------------------


def test_n8n_error_response_raises_n8n_api_error_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    engine = _engine(handler)

    with pytest.raises(N8nApiError) as exc_info:
        engine.create_workflow(_workflow())

    assert exc_info.value.status_code == 500
    assert isinstance(exc_info.value, AutomationEngineError)  # catchable via the provider-neutral base too


def test_n8n_transport_error_raises_n8n_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    engine = _engine(handler)

    with pytest.raises(N8nApiError, match="n8n request failed"):
        engine.activate_workflow("42")


# --- no secrets in the request sent to n8n ----------------------------------


def test_api_key_never_appears_in_request_body():
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"id": "1", "name": "x", "active": False})

    engine = _engine(handler)
    engine.create_workflow(_workflow())

    body = captured["request"].content.decode()
    assert "test-api-key" not in body
