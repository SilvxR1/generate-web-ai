"""HTTP-level tests for app.routers.creative: business assets, reviews,
creative-config, and creative-generations — tenant isolation (Section 18),
asset ownership, review provenance (Section 4), and regeneration safety
(Section 16)."""

import uuid

import pytest
from fastapi.testclient import TestClient

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


def _business_config_payload(**profile_overrides: object) -> dict:
    profile = {"name": "Sacri Barber", "slug": "sacri-barber", "industry": "other"}
    profile.update(profile_overrides)
    return {"schema_version": 1, "business_profile": profile}


def _create_business(client: TestClient, tenant_id: uuid.UUID, *, with_config: bool = True) -> dict:
    payload = {
        "name": "Sacri Barber",
        "slug": "sacri-barber",
        "vertical": "other",
        "raw_description": "Barberia clasica en el centro de la ciudad con mas de cinco anos.",
        "status": "draft",
        "config": _business_config_payload() if with_config else None,
    }
    response = client.post("/businesses", json=payload, headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


# --- Assets --------------------------------------------------------------


def test_create_and_list_business_asset(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    created = client.post(
        f"/businesses/{business['id']}/assets",
        json={
            "kind": "image",
            "category": "project",
            "origin": "uploaded",
            "storage_url": "https://cdn.example.com/photo.jpg",
            "alt_text": "Finished renovation",
        },
        headers=_headers(tenant.id),
    )
    assert created.status_code == 201, created.text
    assert created.json()["origin"] == "uploaded"

    listed = client.get(f"/businesses/{business['id']}/assets", headers=_headers(tenant.id))
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["storage_url"] == "https://cdn.example.com/photo.jpg"


def test_asset_cannot_be_read_or_deleted_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
):
    business = _create_business(client, tenant.id)
    created = client.post(
        f"/businesses/{business['id']}/assets",
        json={"kind": "image", "origin": "uploaded", "storage_url": "https://cdn.example.com/a.jpg"},
        headers=_headers(tenant.id),
    )
    asset_id = created.json()["id"]

    leaked_list = client.get(f"/businesses/{business['id']}/assets", headers=_headers(other_tenant.id))
    assert leaked_list.status_code == 404

    leaked_delete = client.delete(
        f"/businesses/{business['id']}/assets/{asset_id}", headers=_headers(other_tenant.id)
    )
    assert leaked_delete.status_code == 404

    still_there = client.get(f"/businesses/{business['id']}/assets", headers=_headers(tenant.id))
    assert len(still_there.json()) == 1


def test_update_asset_category_reclassifies_without_touching_storage_url(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    created = client.post(
        f"/businesses/{business['id']}/assets",
        json={"kind": "image", "origin": "uploaded", "storage_url": "https://cdn.example.com/a.jpg"},
        headers=_headers(tenant.id),
    )
    asset_id = created.json()["id"]

    updated = client.patch(
        f"/businesses/{business['id']}/assets/{asset_id}",
        json={"category": "hero_candidate"},
        headers=_headers(tenant.id),
    )

    assert updated.status_code == 200
    assert updated.json()["category"] == "hero_candidate"
    assert updated.json()["storage_url"] == "https://cdn.example.com/a.jpg"


# --- Reviews ---------------------------------------------------------------


def test_create_review_stores_body_verbatim(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    body_text = "Pedro kept us informed throughout, very clean and finished on schedule."

    created = client.post(
        f"/businesses/{business['id']}/reviews",
        json={"source": "google", "author_name": "Maria G.", "rating": 5, "body": body_text},
        headers=_headers(tenant.id),
    )

    assert created.status_code == 201, created.text
    assert created.json()["body"] == body_text

    listed = client.get(f"/businesses/{business['id']}/reviews", headers=_headers(tenant.id))
    assert listed.json()[0]["body"] == body_text


def test_reviews_never_leak_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, tenant.id)
    client.post(
        f"/businesses/{business['id']}/reviews",
        json={"body": "Secret review."},
        headers=_headers(tenant.id),
    )

    response = client.get(f"/businesses/{business['id']}/reviews", headers=_headers(other_tenant.id))

    assert response.status_code == 404


# --- Creative config ---------------------------------------------------------


def test_creative_config_defaults_when_business_has_no_config(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id, with_config=False)

    response = client.get(f"/businesses/{business['id']}/creative-config", headers=_headers(tenant.id))

    assert response.status_code == 200
    assert response.json() == {"strategy": "evolve", "level": "basic", "preferred_provider": None}


def test_update_creative_config_requires_existing_business_config(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id, with_config=False)

    response = client.put(
        f"/businesses/{business['id']}/creative-config",
        json={"strategy": "preserve", "level": "premium"},
        headers=_headers(tenant.id),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_business_config"


def test_update_creative_config_roundtrips(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    updated = client.put(
        f"/businesses/{business['id']}/creative-config",
        json={"strategy": "preserve", "level": "professional", "preferred_provider": None},
        headers=_headers(tenant.id),
    )
    assert updated.status_code == 200

    fetched = client.get(f"/businesses/{business['id']}/creative-config", headers=_headers(tenant.id))
    assert fetched.json() == {"strategy": "preserve", "level": "professional", "preferred_provider": None}


# --- Generation --------------------------------------------------------------


def test_generate_website_at_basic_level_completes_via_internal_provider(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(tenant.id),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "internal"
    assert body["status"] == "completed"
    assert body["business_id"] == business["id"]

    history = client.get(f"/businesses/{business['id']}/creative-generations", headers=_headers(tenant.id))
    assert len(history.json()) == 1
    assert history.json()[0]["id"] == body["id"]


def test_generate_at_premium_level_without_higgsfield_configured_fails_clearly_not_silently(
    client: TestClient, tenant: Tenant
):
    """Section 19: no silent downgrade to the free internal provider —
    this must fail with a clear error, and must not be recorded as a
    successful, cheaper-than-requested generation."""
    business = _create_business(client, tenant.id)
    client.put(
        f"/businesses/{business['id']}/creative-config",
        json={"strategy": "evolve", "level": "premium", "preferred_provider": None},
        headers=_headers(tenant.id),
    )

    response = client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(tenant.id),
    )

    assert response.status_code == 502
    assert "premium creative provider" in response.json()["error"]["message"]


def test_generate_without_business_config_is_409(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id, with_config=False)

    response = client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(tenant.id),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_business_config"


def test_generation_history_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, tenant.id)
    client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(tenant.id),
    )

    response = client.get(f"/businesses/{business['id']}/creative-generations", headers=_headers(other_tenant.id))

    assert response.status_code == 404
