"""POST/GET /businesses/{id}/leads/{id}/notes (app.routers.businesses,
P1.3): a lead's simple internal notes — created, listed oldest-first,
and never reachable across a tenant or business boundary."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture()
def lead(session, tenant: Tenant, business: Business) -> Lead:
    lead = Lead(
        tenant_id=tenant.id, business_id=business.id, source="website_form", created_at=datetime.now(UTC), name="Ana"
    )
    session.add(lead)
    session.flush()
    return lead


def test_create_and_list_notes(client: TestClient, tenant: Tenant, business: Business, lead: Lead):
    response = client.post(
        f"/businesses/{business.id}/leads/{lead.id}/notes",
        json={"body": "Llamó y quedó en volver a llamar mañana."},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["body"] == "Llamó y quedó en volver a llamar mañana."
    assert body["lead_id"] == str(lead.id)

    listed = client.get(f"/businesses/{business.id}/leads/{lead.id}/notes", headers={"X-Tenant-Id": str(tenant.id)})
    assert listed.status_code == 200
    assert [n["body"] for n in listed.json()] == ["Llamó y quedó en volver a llamar mañana."]


def test_notes_are_oldest_first(client: TestClient, tenant: Tenant, business: Business, lead: Lead):
    for body in ["first", "second", "third"]:
        client.post(
            f"/businesses/{business.id}/leads/{lead.id}/notes",
            json={"body": body},
            headers={"X-Tenant-Id": str(tenant.id)},
        )

    listed = client.get(f"/businesses/{business.id}/leads/{lead.id}/notes", headers={"X-Tenant-Id": str(tenant.id)})
    assert [n["body"] for n in listed.json()] == ["first", "second", "third"]


def test_create_note_rejects_empty_body(client: TestClient, tenant: Tenant, business: Business, lead: Lead):
    response = client.post(
        f"/businesses/{business.id}/leads/{lead.id}/notes",
        json={"body": ""},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 422


def test_create_note_for_unknown_lead_is_404(client: TestClient, tenant: Tenant, business: Business):
    response = client.post(
        f"/businesses/{business.id}/leads/{uuid.uuid4()}/notes",
        json={"body": "note"},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "lead_not_found"


def test_notes_never_leak_across_tenants(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business: Business, lead: Lead
):
    client.post(
        f"/businesses/{business.id}/leads/{lead.id}/notes",
        json={"body": "secret note"},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    response = client.get(
        f"/businesses/{business.id}/leads/{lead.id}/notes", headers={"X-Tenant-Id": str(other_tenant.id)}
    )

    assert response.status_code == 404


def test_notes_never_leak_across_businesses_within_the_same_tenant(
    client: TestClient, session, tenant: Tenant, business: Business, lead: Lead
):
    from app.domain.enums import BusinessStatus, BusinessVertical

    other_business = Business(
        tenant_id=tenant.id,
        name="Otra Empresa",
        slug="otra-empresa-notes",
        vertical=BusinessVertical.CLINIC,
        raw_description="Clinica dental con dos sedes en Madrid capital y alrededores.",
        status=BusinessStatus.DRAFT,
    )
    session.add(other_business)
    session.flush()

    response = client.get(
        f"/businesses/{other_business.id}/leads/{lead.id}/notes", headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert response.status_code == 404
