"""GET /businesses/{id}/leads (app.routers.businesses): the tenant-scoped
read Studio's leads list uses. Covers empty/populated results, most-recent-
first ordering, unknown business, and that a lead can never be read
through another tenant's (or another business's) id."""

import uuid
from datetime import UTC, datetime, timedelta

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


def _add_lead(session, *, tenant_id: uuid.UUID, business_id: uuid.UUID, created_at: datetime, **fields) -> Lead:
    lead = Lead(tenant_id=tenant_id, business_id=business_id, source="website_form", created_at=created_at, **fields)
    session.add(lead)
    session.flush()
    return lead


def _list_leads(client: TestClient, business_id, tenant_id):
    return client.get(f"/businesses/{business_id}/leads", headers={"X-Tenant-Id": str(tenant_id)})


def test_list_leads_is_empty_when_none_captured(client: TestClient, tenant: Tenant, business: Business):
    response = _list_leads(client, business.id, tenant.id)

    assert response.status_code == 200
    assert response.json() == []


def test_list_leads_returns_captured_fields(client: TestClient, session, tenant: Tenant, business: Business):
    lead = _add_lead(
        session,
        tenant_id=tenant.id,
        business_id=business.id,
        created_at=datetime.now(UTC),
        name="Juan Perez",
        email="juan@example.com",
        phone="+34600000000",
        message="Quiero un presupuesto.",
    )

    body = _list_leads(client, business.id, tenant.id).json()

    assert len(body) == 1
    assert body[0]["id"] == str(lead.id)
    assert body[0]["name"] == "Juan Perez"
    assert body[0]["email"] == "juan@example.com"
    assert body[0]["phone"] == "+34600000000"
    assert body[0]["message"] == "Quiero un presupuesto."
    assert body[0]["status"] == "new"
    assert "created_at" in body[0]


def test_list_leads_orders_most_recent_first(client: TestClient, session, tenant: Tenant, business: Business):
    now = datetime.now(UTC)
    kwargs = {"session": session, "tenant_id": tenant.id, "business_id": business.id}
    oldest = _add_lead(**kwargs, created_at=now - timedelta(days=2), name="Oldest")
    middle = _add_lead(**kwargs, created_at=now - timedelta(days=1), name="Middle")
    newest = _add_lead(**kwargs, created_at=now, name="Newest")

    body = _list_leads(client, business.id, tenant.id).json()

    assert [item["id"] for item in body] == [str(newest.id), str(middle.id), str(oldest.id)]


def test_list_leads_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    response = _list_leads(client, uuid.uuid4(), tenant.id)

    assert response.status_code == 404


def test_list_leads_never_leaks_across_tenants(
    client: TestClient, session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    _add_lead(
        session, tenant_id=tenant.id, business_id=business.id, created_at=datetime.now(UTC), name="Secret Lead"
    )

    response = _list_leads(client, business.id, other_tenant.id)

    assert response.status_code == 404


def test_list_leads_excludes_other_businesses(client: TestClient, session, tenant: Tenant, business: Business):
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
    _add_lead(
        session, tenant_id=tenant.id, business_id=other_business.id, created_at=datetime.now(UTC), name="Not mine"
    )

    body = _list_leads(client, business.id, tenant.id).json()

    assert body == []


def test_list_leads_requires_a_tenant_header(client: TestClient, business: Business):
    response = client.get(f"/businesses/{business.id}/leads")

    assert response.status_code == 422


# --- search/filter (P1.3) -------------------------------------------------


def test_list_leads_filters_by_status(client: TestClient, session, tenant: Tenant, business: Business):
    now = datetime.now(UTC)
    kwargs = {"session": session, "tenant_id": tenant.id, "business_id": business.id}
    new_lead = _add_lead(**kwargs, created_at=now, name="New One")
    contacted = _add_lead(**kwargs, created_at=now, name="Contacted One")
    contacted.status = "contacted"
    session.flush()

    response = _list_leads(client, business.id, tenant.id)
    assert {item["id"] for item in response.json()} == {str(new_lead.id), str(contacted.id)}

    filtered = client.get(
        f"/businesses/{business.id}/leads",
        params={"status": "contacted"},
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert [item["id"] for item in filtered.json()] == [str(contacted.id)]


def test_list_leads_filters_by_source(client: TestClient, session, tenant: Tenant, business: Business):
    fields = {"tenant_id": tenant.id, "business_id": business.id, "created_at": datetime.now(UTC)}
    whatsapp_lead = Lead(source="whatsapp", **fields)
    session.add(whatsapp_lead)
    _add_lead(session=session, **fields, name="Form lead")
    session.flush()

    response = client.get(
        f"/businesses/{business.id}/leads",
        params={"source": "whatsapp"},
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert [item["id"] for item in response.json()] == [str(whatsapp_lead.id)]


def test_list_leads_search_matches_name_email_and_message(
    client: TestClient, session, tenant: Tenant, business: Business
):
    kwargs = {"session": session, "tenant_id": tenant.id, "business_id": business.id, "created_at": datetime.now(UTC)}
    match = _add_lead(**kwargs, name="Ana García", email="someone@example.com", message="hola")
    _add_lead(**kwargs, name="Luis Ruiz", email="luis@example.com", message="otra cosa")

    response = client.get(
        f"/businesses/{business.id}/leads", params={"search": "garcía"}, headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert [item["id"] for item in response.json()] == [str(match.id)]


def test_list_leads_search_is_case_insensitive_substring(
    client: TestClient, session, tenant: Tenant, business: Business
):
    match = _add_lead(
        session, tenant_id=tenant.id, business_id=business.id, created_at=datetime.now(UTC), email="Juan@Example.com"
    )

    response = client.get(
        f"/businesses/{business.id}/leads", params={"search": "juan@example"}, headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert [item["id"] for item in response.json()] == [str(match.id)]
