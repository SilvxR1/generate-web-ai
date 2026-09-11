"""The P2 continuation's canonical lead-API architecture, end to end:

    Website -> POST /public/businesses/{id}/leads -> Lead persisted
             -> best-effort n8n dispatch (only after persistence)

Covers every scenario explicitly required: a persisted Lead always
exists regardless of automation outcome; n8n being unconfigured or
failing never loses the lead; a retry re-attempts dispatch without ever
inserting a duplicate Lead row; and the idempotent `/internal/leads`
endpoint (n8n's own `lead.store` step, now safe to call twice) never
creates a duplicate either. Cross-tenant isolation on the retry endpoint
is verified directly (existing coverage of the underlying
LeadRepository.get_for_business scoping already covers every other
lead-scoped route the same way).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.tenant import Tenant
from app.db.models.workflow import Workflow
from app.dependencies import get_rate_limiter, get_session
from app.domain.enums import NotificationDeliveryStatus, WorkflowStatus
from app.main import app
from app.repositories.lead import LeadRepository
from app.schemas.internal_automation import LeadIngestRequest
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    monkeypatch.setattr("app.routers.public.settings.n8n_base_url", "https://n8n.example.com")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


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


def _active_workflow(session: Session, business) -> Workflow:
    workflow = Workflow(
        tenant_id=business.tenant_id,
        business_id=business.id,
        name="Lead capture",
        status=WorkflowStatus.ACTIVE,
        local_workflow_id=f"{business.slug}-lead-capture",
        n8n_workflow_id="42",
    )
    session.add(workflow)
    session.flush()
    return workflow


def _one_lead(session: Session, tenant_id, business_id):
    [lead] = LeadRepository(session).list_for_business(tenant_id, business_id)
    return lead


# --- Lead always persists, dispatched exactly once on success --------------


def test_lead_persists_and_automation_dispatches_exactly_once(
    client: TestClient, session: Session, tenant: Tenant, business, monkeypatch: pytest.MonkeyPatch
):
    _active_workflow(session, business)
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(
        "app.routers.public.dispatch_lead_to_workflow", lambda **kwargs: calls.append(kwargs["lead"].id)
    )

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201
    lead = _one_lead(session, business.tenant_id, business.id)
    assert lead.automation_dispatch_status == NotificationDeliveryStatus.SENT
    assert calls == [lead.id]  # dispatched exactly once


# --- n8n unavailable/unconfigured never loses the lead ----------------------


def test_lead_persists_when_n8n_is_not_configured(
    client: TestClient, session: Session, business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr("app.routers.public.settings.n8n_base_url", None)  # override the fixture's own override

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201
    lead = _one_lead(session, business.tenant_id, business.id)
    assert lead is not None
    assert lead.automation_dispatch_status == NotificationDeliveryStatus.NOT_CONFIGURED


def test_lead_persists_when_no_active_workflow_exists(client: TestClient, session: Session, business):
    # n8n_base_url IS configured (fixture) but no Workflow row exists at all.
    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201
    lead = _one_lead(session, business.tenant_id, business.id)
    assert lead.automation_dispatch_status == NotificationDeliveryStatus.NOT_CONFIGURED


# --- n8n failure never loses the lead ---------------------------------------


def test_lead_persists_even_when_n8n_dispatch_fails(
    client: TestClient, session: Session, business, monkeypatch: pytest.MonkeyPatch
):
    from app.automation.n8n.dispatch import LeadDispatchError

    _active_workflow(session, business)

    def _raise(**kwargs):
        raise LeadDispatchError("n8n is down")

    monkeypatch.setattr("app.routers.public.dispatch_lead_to_workflow", _raise)

    response = client.post(f"/public/businesses/{business.id}/leads", json=_payload())

    assert response.status_code == 201  # the request itself never fails
    lead = _one_lead(session, business.tenant_id, business.id)
    assert lead is not None
    assert lead.automation_dispatch_status == NotificationDeliveryStatus.FAILED


# --- retry re-attempts dispatch without ever duplicating the Lead ----------


def test_retry_after_failure_succeeds_without_creating_a_duplicate_lead(
    client: TestClient, session: Session, tenant: Tenant, business, monkeypatch: pytest.MonkeyPatch
):
    from app.automation.n8n.dispatch import LeadDispatchError

    _active_workflow(session, business)
    monkeypatch.setattr(
        "app.routers.public.dispatch_lead_to_workflow",
        lambda **kwargs: (_ for _ in ()).throw(LeadDispatchError("n8n is down")),
    )
    client.post(f"/public/businesses/{business.id}/leads", json=_payload())
    lead = _one_lead(session, business.tenant_id, business.id)
    assert lead.automation_dispatch_status == NotificationDeliveryStatus.FAILED

    monkeypatch.setattr("app.routers.businesses.dispatch_lead_to_workflow", lambda **kwargs: None)
    retry_response = client.post(
        f"/businesses/{business.id}/leads/{lead.id}/retry-automation", headers=_headers(tenant.id)
    )

    assert retry_response.status_code == 200, retry_response.text
    assert retry_response.json()["automation_dispatch_status"] == "sent"
    all_leads = LeadRepository(session).list_for_business(business.tenant_id, business.id)
    assert len(all_leads) == 1  # still exactly one Lead row


def test_retry_is_scoped_to_the_correct_tenant(client: TestClient, session: Session, other_tenant: Tenant, business):
    lead = _one_lead_after_creating(client, session, business)

    response = client.post(
        f"/businesses/{business.id}/leads/{lead.id}/retry-automation", headers=_headers(other_tenant.id)
    )

    assert response.status_code == 404  # a different tenant can never reach this business's lead


def _one_lead_after_creating(client: TestClient, session: Session, business):
    client.post(f"/public/businesses/{business.id}/leads", json=_payload())
    return _one_lead(session, business.tenant_id, business.id)


# --- /internal/leads idempotency (n8n's own lead.store, now safe to replay) -


def test_internal_ingest_lead_is_idempotent_when_lead_id_already_exists(session: Session, business):
    from app.routers.internal_automation import ingest_lead

    lead = _one_lead_after_creating_directly(session, business)

    result = ingest_lead(
        LeadIngestRequest(
            tenant_id=business.tenant_id, business_id=business.id, source="webhook", lead_id=lead.id, name="ignored"
        ),
        session=session,
    )

    assert result.id == lead.id
    all_leads = LeadRepository(session).list_for_business(business.tenant_id, business.id)
    assert len(all_leads) == 1  # no duplicate inserted


def test_internal_ingest_lead_still_inserts_when_no_lead_id_given(session: Session, business):
    from app.routers.internal_automation import ingest_lead

    result = ingest_lead(
        LeadIngestRequest(tenant_id=business.tenant_id, business_id=business.id, source="webhook", name="New Lead"),
        session=session,
    )

    assert result.name == "New Lead"
    all_leads = LeadRepository(session).list_for_business(business.tenant_id, business.id)
    assert len(all_leads) == 1


def _one_lead_after_creating_directly(session: Session, business):
    from app.db.models.lead import Lead

    lead = Lead(tenant_id=business.tenant_id, business_id=business.id, source="public_lead_form", name="Direct Lead")
    LeadRepository(session).add(lead)
    return lead
