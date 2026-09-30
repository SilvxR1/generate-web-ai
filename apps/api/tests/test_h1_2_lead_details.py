"""H1.2 — complete lead capture for exported (Higgsfield) site forms.

The public Lead API accepts the form's additional fields as bounded,
labelled `details`, persists them, shows them to Studio and hands them to
n8n; a client `submission_id` makes a retried POST idempotent per business.
Existing callers (no details, no submission id) behave exactly as before.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.automation.n8n.dispatch import dispatch_lead_to_workflow
from app.db.models.business import Business
from app.db.models.lead import Lead
from app.dependencies import get_rate_limiter, get_session
from app.domain.enums import BusinessStatus, BusinessVertical
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter

_DETAILS = [
    {"key": "service", "label": "Tipo de reforma", "value": "Cocina"},
    {"key": "surface_area", "label": "Superficie aproximada", "value": "80"},
]


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _payload(**overrides: object) -> dict:
    payload = {
        "name": "Prueba H1",
        "phone": "600 000 000",
        "message": "Reformar la cocina completa",
        "subject": "Cocina",
        "consent": False,
        "company_website": "",
        "rendered_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    }
    payload.update(overrides)
    return payload


def _post(client: TestClient, business_id: uuid.UUID, **overrides: object) -> httpx.Response:
    return client.post(f"/public/businesses/{business_id}/leads", json=_payload(**overrides))


def _leads(session, business_id: uuid.UUID) -> list[Lead]:
    return list(session.scalars(select(Lead).where(Lead.business_id == business_id)).all())


# --- Valid submissions -------------------------------------------------------------


def test_details_are_persisted_and_visible_to_studio(client, session, tenant, business):
    response = _post(client, business.id, details=_DETAILS, submission_id=str(uuid.uuid4()))
    assert response.status_code == 201 and response.json() == {"received": True}
    [lead] = _leads(session, business.id)
    assert lead.details == _DETAILS
    assert lead.message == "Reformar la cocina completa" and lead.subject == "Cocina"

    listed = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(tenant.id)})
    assert listed.status_code == 200
    assert listed.json()[0]["details"] == _DETAILS


def test_an_existing_style_submission_is_unchanged(client, session, tenant, business):
    response = _post(client, business.id)  # no details, no submission id (every existing site)
    assert response.status_code == 201
    [lead] = _leads(session, business.id)
    assert lead.details is None and lead.client_submission_id is None
    listed = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(tenant.id)})
    assert listed.json()[0]["details"] is None


def test_detail_values_are_trimmed(client, session, business):
    _post(client, business.id, details=[{"key": "surface_area", "label": " Superficie ", "value": "  80 m2  "}])
    [lead] = _leads(session, business.id)
    assert lead.details == [{"key": "surface_area", "label": "Superficie", "value": "80 m2"}]


# --- Invalid / incomplete submissions -------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"phone": None, "email": None},  # no contact method
        {"email": "no-es-un-correo"},
        {"details": [{"key": "Service", "label": "x", "value": "y"}]},  # key must be a lowercase identifier
        {"details": [{"key": "svc; drop", "label": "x", "value": "y"}]},
        {"details": [{"key": "service", "label": "", "value": "y"}]},
        {"details": [{"key": "service", "label": "x", "value": ""}]},
        {"details": [{"key": "service", "label": "x", "value": "v" * 501}]},
        {"details": [{"key": "service", "label": "x", "value": "y", "extra": "z"}]},
        {"details": [{"key": "a", "label": "x", "value": "1"}, {"key": "a", "label": "x", "value": "2"}]},
        {"details": [{"key": f"k{i}", "label": "x", "value": "y"} for i in range(13)]},
        {"submission_id": "not-a-uuid"},
        {"unexpected": "field"},
    ],
)
def test_invalid_submissions_are_rejected_and_nothing_is_stored(client, session, business, overrides):
    response = _post(client, business.id, **overrides)
    assert response.status_code == 422
    assert _leads(session, business.id) == []


# --- Duplicates / retries ---------------------------------------------------------------


def test_a_retried_submission_creates_exactly_one_lead(client, session, business, monkeypatch):
    notifications: list[uuid.UUID] = []
    monkeypatch.setattr(
        "app.routers.public.deliver_internal_notification",
        lambda **kwargs: notifications.append(kwargs["notification"].lead_id),
    )
    submission = str(uuid.uuid4())
    first = _post(client, business.id, details=_DETAILS, submission_id=submission)
    retry = _post(client, business.id, details=_DETAILS, submission_id=submission)
    assert first.status_code == retry.status_code == 201 and first.json() == retry.json()
    assert len(_leads(session, business.id)) == 1
    assert len(notifications) == 1  # the retry never notifies again


def test_distinct_submissions_are_distinct_leads(client, session, business):
    _post(client, business.id, submission_id=str(uuid.uuid4()))
    _post(client, business.id, submission_id=str(uuid.uuid4()))
    assert len(_leads(session, business.id)) == 2


def test_a_submission_id_never_crosses_businesses(client, session, other_tenant, business):
    other = Business(
        tenant_id=other_tenant.id,
        name="Otra",
        slug="otra",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="x",
        status=BusinessStatus.DRAFT,
    )
    session.add(other)
    session.flush()
    submission = str(uuid.uuid4())
    _post(client, business.id, submission_id=submission)
    _post(client, other.id, submission_id=submission)
    assert len(_leads(session, business.id)) == 1 and len(_leads(session, other.id)) == 1
    assert _leads(session, other.id)[0].tenant_id == other_tenant.id


# --- Malicious submissions ----------------------------------------------------------------


def test_the_honeypot_still_drops_a_bot_with_details(client, session, business):
    response = _post(client, business.id, details=_DETAILS, company_website="https://spam.example")
    assert response.status_code == 201 and response.json() == {"received": True}  # indistinguishable
    assert _leads(session, business.id) == []


def test_markup_in_details_is_stored_as_inert_text(client, session, tenant, business):
    payload = [{"key": "notes", "label": "Notas", "value": "<script>alert(1)</script>"}]
    _post(client, business.id, details=payload)
    listed = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(tenant.id)})
    assert listed.json()[0]["details"] == payload  # data, returned verbatim as JSON text (Studio renders text)


def test_other_tenants_cannot_read_the_details(client, session, other_tenant, business):
    _post(client, business.id, details=_DETAILS)
    response = client.get(f"/businesses/{business.id}/leads", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert response.status_code == 404


# --- Automation ------------------------------------------------------------------------------


def test_n8n_receives_the_details_additively(session, tenant, business):
    lead = Lead(
        tenant_id=tenant.id, business_id=business.id, source="website_form", name="x", phone="1", details=_DETAILS
    )
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200)

    class _Workflow:
        local_workflow_id = "wf-1"

    dispatch_lead_to_workflow(
        lead=lead,
        workflow=_Workflow(),  # type: ignore[arg-type]
        n8n_base_url="https://n8n.example.com",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert captured[0]["details"] == _DETAILS
    assert {"lead_id", "name", "email", "phone", "message", "subject", "consent"} <= set(captured[0])
