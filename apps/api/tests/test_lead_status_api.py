"""PATCH /businesses/{id}/leads/{id}/status (app.routers.businesses): the
only write path onto Lead.status. Covers a normal transition, that no
other field can be smuggled in, unknown lead, and that a lead can never
be updated through another tenant's or another business's id."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db.models.business import Business
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.domain.enums import BusinessStatus, BusinessVertical
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


def _add_lead(session, *, tenant_id: uuid.UUID, business_id: uuid.UUID, **fields) -> Lead:
    lead = Lead(
        tenant_id=tenant_id,
        business_id=business_id,
        source="website_form",
        created_at=datetime.now(UTC),
        **fields,
    )
    session.add(lead)
    session.flush()
    return lead


def _update_status(client: TestClient, business_id, lead_id, tenant_id, status: str | None = "contacted"):
    body = {} if status is None else {"status": status}
    return client.patch(
        f"/businesses/{business_id}/leads/{lead_id}/status",
        json=body,
        headers={"X-Tenant-Id": str(tenant_id)},
    )


def test_new_lead_defaults_to_new_status(session, tenant: Tenant, business: Business):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    assert lead.status == "new"


def test_update_lead_status_changes_it(client: TestClient, session, tenant: Tenant, business: Business):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    response = _update_status(client, business.id, lead.id, tenant.id, "contacted")

    assert response.status_code == 200
    assert response.json()["status"] == "contacted"
    assert lead.status == "contacted"


@pytest.mark.parametrize("status", ["new", "contacted", "qualified", "won", "lost"])
def test_update_lead_status_accepts_every_enum_value(
    client: TestClient, session, tenant: Tenant, business: Business, status: str
):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    response = _update_status(client, business.id, lead.id, tenant.id, status)

    assert response.status_code == 200
    assert response.json()["status"] == status


def test_update_lead_status_rejects_an_unknown_value(client: TestClient, session, tenant: Tenant, business: Business):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    response = _update_status(client, business.id, lead.id, tenant.id, "archived")

    assert response.status_code == 422
    assert lead.status == "new"


def test_update_lead_status_rejects_extra_fields(client: TestClient, session, tenant: Tenant, business: Business):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    response = client.patch(
        f"/businesses/{business.id}/leads/{lead.id}/status",
        json={"status": "contacted", "notes": "not allowed"},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 422
    assert lead.status == "new"


def test_update_lead_status_for_unknown_lead_is_404(client: TestClient, tenant: Tenant, business: Business):
    response = _update_status(client, business.id, uuid.uuid4(), tenant.id, "contacted")

    assert response.status_code == 404


def test_update_lead_status_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    response = _update_status(client, uuid.uuid4(), uuid.uuid4(), tenant.id, "contacted")

    assert response.status_code == 404


def test_update_lead_status_never_crosses_tenants(
    client: TestClient, session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    lead = _add_lead(session, tenant_id=tenant.id, business_id=business.id)

    response = _update_status(client, business.id, lead.id, other_tenant.id, "contacted")

    assert response.status_code == 404
    assert lead.status == "new"


def test_update_lead_status_never_crosses_businesses(client: TestClient, session, tenant: Tenant, business: Business):
    other_business = Business(
        tenant_id=tenant.id,
        name="Otra Empresa",
        slug="otra-empresa",
        vertical=BusinessVertical.CLINIC,
        raw_description="Clinica dental con dos sedes en Madrid capital y alrededores.",
        status=BusinessStatus.DRAFT,
    )
    session.add(other_business)
    session.flush()
    lead = _add_lead(session, tenant_id=tenant.id, business_id=other_business.id)

    response = _update_status(client, business.id, lead.id, tenant.id, "contacted")

    assert response.status_code == 404
    assert lead.status == "new"


def test_update_lead_status_requires_a_tenant_header(client: TestClient, business: Business):
    response = client.patch(f"/businesses/{business.id}/leads/{uuid.uuid4()}/status", json={"status": "contacted"})

    assert response.status_code == 422
