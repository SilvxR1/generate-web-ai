"""GET .../website/versions and POST .../website/versions/{id}/rollback
(app.routers.businesses): the HTTP boundary around
app.publishing.versions — empty list before any publish, versions
accumulate across publishes, rollback republishes an old version and
appends a new one, rollback for an unknown version is a 404, tenant
isolation. Website-publish orchestration itself is already covered by
test_website_publish_service.py/test_website_versions_service.py — this
file is purely about the HTTP boundary, so get_website_publisher is
overridden with the FakePublisher fake rather than a real httpx mock."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_session, get_website_publisher
from app.main import app
from app.publishing.publisher import WebsiteArtifact
from tests.test_website_publish_service import FakePublisher

SITE_CONFIG = {
    "brand": {"name": "Reforma Casa Valencia", "tagline": "Reformas integrales"},
    "theme": {
        "colors": {
            "primary": "#111827",
            "secondary": "#6b7280",
            "accent": "#2563eb",
            "background": "#ffffff",
            "foreground": "#111827",
        },
        "fonts": {"sans": "Inter, sans-serif"},
        "radius": {"base": "0.5rem", "lg": "1rem"},
    },
    "seo": {"title": "Reforma Casa Valencia", "description": "Empresa de reformas en Valencia."},
    "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {"heading": "Tu reforma, sin sorpresas"}}]}],
}


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_website_publisher, None)


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    artifact = WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: artifact)


def _create_business(client: TestClient, tenant_id: uuid.UUID, **overrides: object) -> dict:
    payload = {
        "name": "Reforma Casa Valencia",
        "slug": "reforma-casa-valencia",
        "vertical": "home_renovation",
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": "draft",
    }
    payload.update(overrides)
    response = client.post("/businesses", json=payload, headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    response = client.post(
        f"/businesses/{business_id}/website/publish", json=SITE_CONFIG, headers={"X-Tenant-Id": str(tenant_id)}
    )
    assert response.status_code == 200, response.text
    return response


def _list_versions(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.get(f"/businesses/{business_id}/website/versions", headers={"X-Tenant-Id": str(tenant_id)})


def _rollback(client: TestClient, business_id: str, version_id: str, tenant_id: uuid.UUID):
    return client.post(
        f"/businesses/{business_id}/website/versions/{version_id}/rollback",
        headers={"X-Tenant-Id": str(tenant_id)},
    )


def test_list_versions_is_empty_before_any_publish(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = _list_versions(client, business["id"], tenant.id)

    assert response.status_code == 200
    assert response.json() == []


def test_versions_accumulate_across_publishes_most_recent_first(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)
    _publish(client, business["id"], tenant.id)

    response = _list_versions(client, business["id"], tenant.id)

    assert response.status_code == 200
    versions = response.json()
    assert len(versions) == 2
    assert versions[0]["is_current"] is True
    assert versions[1]["is_current"] is False


def test_rollback_republishes_an_old_version_and_appends_a_new_one(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)
    _publish(client, business["id"], tenant.id)
    versions = _list_versions(client, business["id"], tenant.id).json()
    oldest_version_id = versions[-1]["id"]

    response = _rollback(client, business["id"], oldest_version_id, tenant.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "live"

    versions_after = _list_versions(client, business["id"], tenant.id).json()
    assert len(versions_after) == 3
    assert versions_after[0]["is_current"] is True
    assert versions_after[0]["id"] != oldest_version_id


def test_rollback_to_an_unknown_version_is_a_404(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)

    response = _rollback(client, business["id"], str(uuid.uuid4()), tenant.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "website_version_not_found"


def test_versions_never_leak_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, other_tenant.id)
    _publish(client, business["id"], other_tenant.id)

    response = _list_versions(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_rollback_never_crosses_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, other_tenant.id)
    _publish(client, business["id"], other_tenant.id)
    versions = _list_versions(client, business["id"], other_tenant.id).json()

    response = _rollback(client, business["id"], versions[0]["id"], tenant.id)

    assert response.status_code == 404
