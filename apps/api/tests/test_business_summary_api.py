"""GET /business-summaries (app.routers.businesses): the batch-loaded
listing Studio's dashboard uses to show every business plus its
persisted website/automation status without one request per business.
Tenant isolation follows the same pattern as GET /businesses (see
test_business_api_isolation.py) — a caller only ever sees their own
tenant's businesses here, regardless of what other tenants have.

Lives on its own /business-summaries prefix rather than
/businesses/summary specifically because the latter collided with GET
/businesses/{business_id} (FastAPI tried to parse "summary" as a UUID
and returned 422) — see business_summaries_router's own comment in
app.routers.businesses. test_summary_path_does_not_collide_with_business_id_route
below guards against that regression coming back.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.db.models.workflow import Workflow
from app.dependencies import get_session
from app.domain.enums import BusinessStatus, BusinessVertical, WebsiteStatus, WorkflowStatus
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


def _make_business(session, tenant_id: uuid.UUID, *, name: str, slug: str, config: dict | None = None) -> Business:
    business = Business(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Empresa de reformas integrales en Valencia con mas de diez anos de experiencia.",
        status=BusinessStatus.DRAFT,
        config=config,
    )
    session.add(business)
    session.flush()
    return business


def test_summary_scoped_to_tenant_excludes_other_tenants_businesses(
    client: TestClient, session, tenant: Tenant, other_tenant: Tenant
):
    _make_business(session, tenant.id, name="Reforma Pepe", slug="reforma-pepe")
    _make_business(session, other_tenant.id, name="Business B", slug="business-b")

    response = client.get("/business-summaries", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    body = response.json()
    assert [b["slug"] for b in body] == ["reforma-pepe"]


def test_summary_path_does_not_collide_with_business_id_route(client: TestClient, tenant: Tenant):
    """The regression this file guards against: GET /business-summaries
    must be resolved by business_summaries_router, never by
    GET /businesses/{business_id} trying (and failing) to parse a path
    segment as a UUID. Asserting a real 200 here — not just "not a
    422" — proves the correct handler ran, on a tenant with zero
    businesses so an empty list is the only possible correct body.
    """
    response = client.get("/business-summaries", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    assert response.json() == []


def test_summary_missing_tenant_header_is_rejected(client: TestClient):
    response = client.get("/business-summaries")
    assert response.status_code == 422


def test_summary_unknown_tenant_is_rejected(client: TestClient):
    response = client.get("/business-summaries", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_summary_business_with_no_website_or_automation_reports_null_for_both(
    client: TestClient, session, tenant: Tenant
):
    _make_business(session, tenant.id, name="Reforma Pepe", slug="reforma-pepe")

    response = client.get("/business-summaries", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    [summary] = response.json()
    assert summary["name"] == "Reforma Pepe"
    assert summary["vertical"] == "home_renovation"
    assert summary["status"] == "draft"
    assert summary["website"] is None
    assert summary["automation"] is None
    assert summary["location"] is None
    assert "config" not in summary


def test_summary_reflects_persisted_website_and_automation_state_without_n_plus_one(
    client: TestClient, session, tenant: Tenant
):
    business = _make_business(
        session,
        tenant.id,
        name="Reforma Pepe",
        slug="reforma-pepe",
        config={
            "schema_version": 1,
            "business_profile": {
                "name": "Reforma Pepe",
                "slug": "reforma-pepe",
                "industry": "home_renovation",
                "location": {"city": "Valencia", "country": "ES"},
            },
        },
    )
    session.add(
        Website(
            tenant_id=tenant.id,
            business_id=business.id,
            status=WebsiteStatus.LIVE,
            deploy_url="https://site-reforma-pepe.workers.dev/",
            deployed_at=datetime.now(UTC),
        )
    )
    session.add(
        Workflow(
            tenant_id=tenant.id,
            business_id=business.id,
            name="Reforma Pepe — Lead capture",
            status=WorkflowStatus.ACTIVE,
            local_workflow_id="reforma-pepe-lead-capture",
            required_capabilities=["lead.store"],
        )
    )
    session.flush()

    # A second business belonging to the same tenant, with no website or
    # automation yet — proves the batch queries don't require every
    # business to have one of these rows, and don't leak one business's
    # state onto another's.
    _make_business(session, tenant.id, name="Sacri Barber", slug="sacri-barber")

    response = client.get("/business-summaries", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    body = {b["slug"]: b for b in response.json()}

    reforma = body["reforma-pepe"]
    assert reforma["location"] == {"city": "Valencia", "region": None, "country": "ES", "postal_code": None}
    assert reforma["website"] == {"status": "live", "live_url": "https://site-reforma-pepe.workers.dev/"}
    assert reforma["automation"] == {"status": "active", "active": True}

    sacri = body["sacri-barber"]
    assert sacri["website"] is None
    assert sacri["automation"] is None
