"""BusinessConfig API isolation: Tenant A cannot read/update/delete/list
Tenant B's businesses through the HTTP API — the "Isolation" bullet of
the business-configuration-system phase.

IMPORTANT — this is NOT a test of real authentication, because none
exists yet. `get_current_tenant_id` (app.dependencies) trusts whatever
`X-Tenant-Id` header the caller sends, as long as it names a real
Tenant. What these tests actually prove: given a caller presenting
tenant A's id, they cannot reach tenant B's data through `business_id`
alone. They do NOT prove that only tenant A's real members can present
tenant A's id in the first place — that's what real authentication still
needs to add, inside `get_current_tenant_id`, without any route or
service code changing (see that function's docstring for the seam this
is designed around).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.main import app


@pytest.fixture()
def client(session):
    def _override_get_session():
        # Must itself be a generator function — FastAPI detects
        # generator-shaped dependencies by inspecting the callable, so a
        # plain `lambda: iter([session])` is treated as returning the
        # iterator itself rather than yielding a value from it.
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _business_payload(**overrides: object) -> dict:
    payload = {
        "name": "Sacri Barber",
        "slug": "sacri-barber",
        "vertical": "other",
        "raw_description": "Barberia clasica en el centro de la ciudad con mas de cinco anos de trayectoria.",
        "status": "draft",
        "config": None,
    }
    payload.update(overrides)
    return payload


def _create_business(client: TestClient, tenant_id: uuid.UUID, **overrides: object) -> dict:
    response = client.post("/businesses", json=_business_payload(**overrides), headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def test_missing_tenant_header_is_rejected(client: TestClient):
    response = client.get("/businesses")
    assert response.status_code == 422


def test_unknown_tenant_header_is_rejected(client: TestClient):
    response = client.get("/businesses", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_malformed_tenant_header_is_rejected(client: TestClient):
    response = client.get("/businesses", headers={"X-Tenant-Id": "not-a-uuid"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_tenant_header"


def test_tenant_a_cannot_read_tenant_bs_business(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business_b = _create_business(client, other_tenant.id, slug="business-b")

    response = client.get(f"/businesses/{business_b['id']}", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 404


def test_tenant_a_cannot_update_tenant_bs_business(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business_b = _create_business(client, other_tenant.id, slug="business-b")

    response = client.put(
        f"/businesses/{business_b['id']}",
        json=_business_payload(name="Hijacked", slug="business-b"),
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 404


def test_tenant_a_cannot_delete_tenant_bs_business(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business_b = _create_business(client, other_tenant.id, slug="business-b")

    response = client.delete(f"/businesses/{business_b['id']}", headers={"X-Tenant-Id": str(tenant.id)})
    assert response.status_code == 404

    still_there = client.get(f"/businesses/{business_b['id']}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert still_there.status_code == 200


def test_tenant_a_list_excludes_tenant_bs_businesses(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _create_business(client, tenant.id, slug="business-a")
    _create_business(client, other_tenant.id, slug="business-b")

    response = client.get("/businesses", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    assert [b["slug"] for b in response.json()] == ["business-a"]


def test_full_crud_roundtrip_scoped_to_one_tenant(client: TestClient, tenant: Tenant):
    created = _create_business(client, tenant.id)
    business_id = created["id"]

    fetched = client.get(f"/businesses/{business_id}", headers={"X-Tenant-Id": str(tenant.id)})
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Sacri Barber"

    updated = client.put(
        f"/businesses/{business_id}",
        json=_business_payload(name="Sacri Barber Updated", status="active"),
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Sacri Barber Updated"
    assert updated.json()["status"] == "active"

    deleted = client.delete(f"/businesses/{business_id}", headers={"X-Tenant-Id": str(tenant.id)})
    assert deleted.status_code == 204

    gone = client.get(f"/businesses/{business_id}", headers={"X-Tenant-Id": str(tenant.id)})
    assert gone.status_code == 404


def test_create_rejects_duplicate_slug_within_tenant_via_api(client: TestClient, tenant: Tenant):
    _create_business(client, tenant.id, slug="sacri-barber")

    response = client.post(
        "/businesses", json=_business_payload(name="Duplicate"), headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slug_conflict"
