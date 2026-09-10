"""HTTP-level tests for the website-draft endpoints
(app.routers.creative): tenant isolation and the explicit
generate -> build -> approve -> publish lifecycle, mirroring
test_creative_api.py's fixtures."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.main import app
from app.publishing.publisher import PublishedSite, WebsiteArtifact


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    monkeypatch.setattr(
        "app.publishing.drafts.build_site", lambda site_config: WebsiteArtifact(files={"index.html": b"<html></html>"})
    )
    monkeypatch.setattr(
        "app.publishing.service.build_site", lambda site_config: WebsiteArtifact(files={"index.html": b"<html></html>"})
    )

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


_SITE_CONFIG = {
    "brand": {"name": "Sacri Barber"},
    "theme": {
        "colors": {
            "primary": "#111827",
            "secondary": "#6b7280",
            "accent": "#2563eb",
            "background": "#ffffff",
            "foreground": "#111827",
        },
        "fonts": {"sans": "Inter"},
        "radius": {"base": "0.5rem", "lg": "1rem"},
    },
    "seo": {"title": "Sacri Barber", "description": "Barberia clasica."},
    "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {"heading": "Bienvenido"}}]}],
}


def _create_draft(client: TestClient, business_id, tenant_id):
    return client.post(
        f"/businesses/{business_id}/website-drafts",
        json={"site_config": _SITE_CONFIG, "creative_generation_id": None},
        headers=_headers(tenant_id),
    )


def test_create_draft_never_touches_the_live_website(client: TestClient, tenant: Tenant, business):
    response = _create_draft(client, business.id, tenant.id)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"

    website = client.get(f"/businesses/{business.id}/website", headers=_headers(tenant.id))
    assert website.status_code == 200
    assert website.json() is None  # still nothing published


def test_publish_before_approval_is_rejected(client: TestClient, tenant: Tenant, business):
    draft = _create_draft(client, business.id, tenant.id).json()

    response = client.post(
        f"/businesses/{business.id}/website-drafts/{draft['id']}/publish", headers=_headers(tenant.id)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "website_draft_not_approved"


def test_full_approve_then_publish_updates_the_live_website(
    client: TestClient, tenant: Tenant, business, monkeypatch: pytest.MonkeyPatch
):
    from app.dependencies import get_website_publisher
    from app.publishing.publisher import WebsitePublisher

    class FakePublisher(WebsitePublisher):
        def publish(self, *, site_id, artifact):
            return PublishedSite(deployment_id="dep-1", url="https://example.pages.dev", live=True)

        def get_status(self, deployment_id):
            raise NotImplementedError

        def unpublish(self, deployment_id):
            pass

    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher()
    try:
        draft = _create_draft(client, business.id, tenant.id).json()

        approved = client.post(
            f"/businesses/{business.id}/website-drafts/{draft['id']}/approve", headers=_headers(tenant.id)
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"

        published = client.post(
            f"/businesses/{business.id}/website-drafts/{draft['id']}/publish", headers=_headers(tenant.id)
        )
        assert published.status_code == 200
        assert published.json()["status"] == "live"

        website = client.get(f"/businesses/{business.id}/website", headers=_headers(tenant.id))
        assert website.json()["status"] == "live"
    finally:
        app.dependency_overrides.pop(get_website_publisher, None)


def test_drafts_never_leak_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant, business):
    _create_draft(client, business.id, tenant.id)

    response = client.get(f"/businesses/{business.id}/website-drafts", headers=_headers(other_tenant.id))

    assert response.status_code == 404


def test_approve_a_draft_through_another_tenant_is_rejected(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    draft = _create_draft(client, business.id, tenant.id).json()

    response = client.post(
        f"/businesses/{business.id}/website-drafts/{draft['id']}/approve", headers=_headers(other_tenant.id)
    )

    assert response.status_code == 404
