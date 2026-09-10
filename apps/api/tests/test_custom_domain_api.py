"""POST/GET/POST .../refresh/DELETE .../businesses/{id}/website/domain
(app.routers.businesses): the HTTP boundary around
app.publishing.domains — missing Cloudflare configuration, attach
requiring a live website first, invalid domain syntax rejected,
tenant isolation, and idempotent detach. Cloudflare's own wire protocol
is already covered by test_cloudflare_domain_provider.py and
attach/detach orchestration by test_custom_domain_service.py — this
file is purely about the HTTP boundary (status codes, error-code
mapping), so the website-publish and domain-provider dependencies are
both overridden with fakes rather than a real httpx mock."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_domain_provider, get_session, get_website_publisher
from app.main import app
from app.publishing.publisher import WebsiteArtifact
from tests.test_custom_domain_service import FakeDomainProvider
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_website_publisher, None)
        app.dependency_overrides.pop(get_domain_provider, None)


@pytest.fixture(autouse=True)
def _cloudflare_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "cloudflare_account_id", "acct-1")
    monkeypatch.setattr(settings, "cloudflare_api_token", "cf-super-secret-api-token")


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


def _publish_website(client: TestClient, business_id: str, tenant_id: uuid.UUID) -> None:
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher()
    response = client.post(
        f"/businesses/{business_id}/website/publish", json=SITE_CONFIG, headers={"X-Tenant-Id": str(tenant_id)}
    )
    assert response.status_code == 200, response.text


def _attach(client: TestClient, business_id: str, tenant_id: uuid.UUID, domain: str = "example.com"):
    return client.post(
        f"/businesses/{business_id}/website/domain", json={"domain": domain}, headers={"X-Tenant-Id": str(tenant_id)}
    )


def _get_domain(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.get(f"/businesses/{business_id}/website/domain", headers={"X-Tenant-Id": str(tenant_id)})


def _refresh_domain(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/website/domain/refresh", headers={"X-Tenant-Id": str(tenant_id)})


def _detach_domain(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.delete(f"/businesses/{business_id}/website/domain", headers={"X-Tenant-Id": str(tenant_id)})


# --- attach -------------------------------------------------------------


def test_attach_requires_a_live_website_first(client: TestClient, tenant: Tenant):
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()
    business = _create_business(client, tenant.id)

    response = _attach(client, business["id"], tenant.id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "website_not_live"


def test_attach_success_returns_the_cname_target(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish_website(client, business["id"], tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()

    response = _attach(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["domain"] == "example.com"
    assert body["status"] == "pending_verification"
    assert body["cname_target"] == f"site-{business['id'].replace('-', '')}.pages.dev"


def test_attach_rejects_a_syntactically_invalid_domain(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish_website(client, business["id"], tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()

    response = _attach(client, business["id"], tenant.id, domain="not a domain")

    assert response.status_code == 422


def test_missing_cloudflare_config_is_rejected(client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch):
    business = _create_business(client, tenant.id)
    _publish_website(client, business["id"], tenant.id)
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)

    response = _attach(client, business["id"], tenant.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "domain_provider_not_configured"


def test_attach_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    business = _create_business(client, other_tenant.id)
    _publish_website(client, business["id"], other_tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()

    response = _attach(client, business["id"], tenant.id)

    assert response.status_code == 404


# --- get / refresh --------------------------------------------------------


def test_get_domain_returns_null_before_any_attach(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = _get_domain(client, business["id"], tenant.id)

    assert response.status_code == 200
    assert response.json() is None


def test_refresh_reflects_the_providers_current_status(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish_website(client, business["id"], tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()
    _attach(client, business["id"], tenant.id)

    response = _refresh_domain(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"  # FakeDomainProvider.get_status always reports active


# --- detach -----------------------------------------------------------------


def test_detach_without_any_prior_attach_is_a_404(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()

    response = _detach_domain(client, business["id"], tenant.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "custom_domain_not_found"


def test_detach_success_then_get_reports_null_again(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)
    _publish_website(client, business["id"], tenant.id)
    app.dependency_overrides[get_domain_provider] = lambda: FakeDomainProvider()
    _attach(client, business["id"], tenant.id)

    response = _detach_domain(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "removed"

    reloaded = _get_domain(client, business["id"], tenant.id)
    assert reloaded.json() is None
