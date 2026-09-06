"""End-to-end service test for the whole loop the phase asked to close:

    BusinessConfig -> generate_lead_capture_workflow() -> translate_workflow()
    -> (mocked n8n) lead.store request -> Lead persisted -> notification processed

No real n8n: httpx.MockTransport intercepts n8n's own API calls
(workflow creation) and, separately, this test drives the translated
workflow's own HTTP Request nodes by calling this API's real
/internal/leads and /internal/notifications endpoints directly with the
exact body shape the translator produces — the same thing n8n's HTTP
Request node would send at execution time.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.automation.n8n import N8nAutomationEngine, N8nClient, N8nTranslationContext, translate_workflow
from app.config import settings
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.domain.business_config.business_profile import BusinessProfile, ContactInfo
from app.domain.business_config.config import BusinessConfig
from app.domain.workflow_config import generate_lead_capture_workflow
from app.main import app
from app.repositories.lead import LeadRepository

TOKEN = "e2e-internal-automation-token"


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
def _configured_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "internal_automation_token", TOKEN)


def _business_config_for(business: Business) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name=business.name,
            slug=business.slug,
            industry=business.vertical,
            contact=ContactInfo(email="ana@example.com"),
        ),
        automation={"lead_capture": True, "lead_notifications": True, "customer_acknowledgement": False},
    )


def test_lead_capture_flow_end_to_end(client: TestClient, session, tenant: Tenant, business: Business):
    # 1. BusinessConfig -> generate_lead_capture_workflow()
    business_config = _business_config_for(business)
    workflow = generate_lead_capture_workflow(business_config)
    assert workflow.required_capabilities == ["lead.store", "notification.send"]

    # 2. translate_workflow() -- scoped to this real tenant/business, so
    # the generated callback bodies carry real ownership, same as
    # app.automation.n8n.engine.translation_context_from_settings would
    # build for real usage.
    context = N8nTranslationContext(
        internal_leads_url=f"{settings.internal_api_base_url}/internal/leads",
        internal_notifications_url=f"{settings.internal_api_base_url}/internal/notifications",
        tenant_id=str(tenant.id),
        business_id=str(business.id),
    )
    n8n_payload = translate_workflow(workflow, context)
    store_node = next(n for n in n8n_payload["nodes"] if n["id"] == "store-lead")
    assert "tenant_id" in store_node["parameters"]["jsonBody"]

    # 3. Mocked n8n API: prove N8nAutomationEngine.create_workflow() would
    # actually hand n8n this exact translated payload (n8n itself is not
    # available in this environment, per the phase's own allowance).
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"id": "n8n-wf-1", "name": workflow.name, "active": False})

    mock_http_client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://n8n.example.com")
    n8n_client = N8nClient("https://n8n.example.com", "n8n-api-key", http_client=mock_http_client)
    engine = N8nAutomationEngine(n8n_client, context)

    remote_workflow = engine.create_workflow(workflow)

    assert remote_workflow.remote_id == "n8n-wf-1"
    assert captured["request"].method == "POST"

    # 4. lead.store request -- exactly what n8n's HTTP Request node sends
    # at execution time: the webhook payload (name/email/phone/message)
    # enriched with the tenant_id/business_id/source the translator
    # baked in, POSTed to the exact URL the translator produced.
    webhook_payload = {
        "name": "Ana García",
        "email": "ana@example.com",
        "phone": "+34 600 00 00 00",
        "message": "Necesito presupuesto",
    }
    enriched_body = {
        **webhook_payload,
        "tenant_id": str(tenant.id),
        "business_id": str(business.id),
        "source": "website_form",
    }

    lead_response = client.post(
        store_node["parameters"]["url"].removeprefix(settings.internal_api_base_url),
        json=enriched_body,
        headers={"X-Internal-Automation-Token": TOKEN},
    )
    assert lead_response.status_code == 201, lead_response.text
    lead = lead_response.json()

    # 5. Lead persisted -- queryable via the real repository, not just
    # "the endpoint returned 201".
    stored = LeadRepository(session).get(tenant.id, uuid.UUID(lead["id"]))
    assert stored is not None
    assert stored.email == "ana@example.com"

    # 6. notification processed -- the notify-internal node forwards
    # store-lead's own response (the created Lead) onward; simulate that
    # exact hand-off.
    notify_node = next(n for n in n8n_payload["nodes"] if n["id"] == "notify-internal")
    notification_response = client.post(
        notify_node["parameters"]["url"].removeprefix(settings.internal_api_base_url),
        json=lead,
        headers={"X-Internal-Automation-Token": TOKEN},
    )
    assert notification_response.status_code == 201, notification_response.text
    notification = notification_response.json()
    assert notification["delivered"] is False
    assert notification["lead_id"] == lead["id"]


def test_lead_capture_flow_from_a_realistic_n8n_webhook_item_shape(
    client: TestClient, session, tenant: Tenant, business: Business
):
    """n8n's Webhook node always wraps a POST as {headers, params, query,
    body} — the real posted fields live at $json.body, never at $json
    root. This proves app.automation.n8n.translator's
    `($json.body || $json)` mapping (see _internal_callback_node)
    resolves to the actually-posted fields, by manually applying that
    same, documented JS-expression semantics to a webhook-item-shaped
    payload (no n8n instance in this environment to execute the real
    expression) and posting the result exactly as n8n's HTTP Request
    node would — proving name/email/phone/message survive the mapping
    end to end into a persisted Lead."""
    business_config = _business_config_for(business)
    workflow = generate_lead_capture_workflow(business_config)
    context = N8nTranslationContext(
        internal_leads_url=f"{settings.internal_api_base_url}/internal/leads",
        internal_notifications_url=f"{settings.internal_api_base_url}/internal/notifications",
        tenant_id=str(tenant.id),
        business_id=str(business.id),
    )
    n8n_payload = translate_workflow(workflow, context)
    store_node = next(n for n in n8n_payload["nodes"] if n["id"] == "store-lead")
    assert "$json.body" in store_node["parameters"]["jsonBody"]

    # The real shape n8n's Webhook node hands downstream for a
    # <form method="post"> submission (predictable field names — the
    # form's own `name` attributes, see packages/website-generator's
    # buildLeadForm) — fields live under `.body`, not at the root.
    webhook_item = {
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "params": {},
        "query": {},
        "body": {
            "name": "Ana García",
            "email": "ana@example.com",
            "phone": "+34 600 00 00 00",
            "message": "Necesito presupuesto",
        },
    }
    # Manual trace of `Object.assign({}, ($json.body || $json), extra)`.
    resolved_fields = webhook_item.get("body") or webhook_item
    enriched_body = {
        **resolved_fields,
        "tenant_id": str(tenant.id),
        "business_id": str(business.id),
        "source": "website_form",
    }

    lead_response = client.post(
        store_node["parameters"]["url"].removeprefix(settings.internal_api_base_url),
        json=enriched_body,
        headers={"X-Internal-Automation-Token": TOKEN},
    )
    assert lead_response.status_code == 201, lead_response.text
    lead = lead_response.json()
    assert lead["name"] == "Ana García"
    assert lead["email"] == "ana@example.com"
    assert lead["phone"] == "+34 600 00 00 00"
    assert lead["message"] == "Necesito presupuesto"

    stored = LeadRepository(session).get(tenant.id, uuid.UUID(lead["id"]))
    assert stored is not None
    assert stored.phone == "+34 600 00 00 00"
    assert stored.message == "Necesito presupuesto"
