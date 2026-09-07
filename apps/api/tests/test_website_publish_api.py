"""POST /businesses/{id}/website/publish and GET /businesses/{id}/website
(app.routers.businesses): the HTTP boundary around publish_website and
get_website_state — missing Cloudflare configuration, publish failure,
reload returning the persisted live URL/status, tenant isolation, and
that the Cloudflare API token never appears in any response body.

app.publishing.build.build_site is monkeypatched to a fake, instant
build here — these tests are about the HTTP boundary (status codes,
error-code mapping, tenant isolation), not build fidelity (see
test_site_builder_integration.py) or Cloudflare's wire protocol (see
test_cloudflare_pages_publisher.py)."""

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_session, get_website_publisher
from app.main import app
from app.publishing.cloudflare import CloudflarePagesClient, CloudflarePagesPublisher
from app.publishing.publisher import WebsiteArtifact

API_TOKEN = "cf-super-secret-api-token"

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
    "pages": [
        {
            "path": "/",
            "blocks": [{"type": "hero", "content": {"heading": "Tu reforma, sin sorpresas"}}],
        }
    ],
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


@pytest.fixture(autouse=True)
def _cloudflare_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "cloudflare_account_id", "acct-1")
    monkeypatch.setattr(settings, "cloudflare_api_token", API_TOKEN)


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    artifact = WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: artifact)


@pytest.fixture(autouse=True)
def _fake_wrangler(monkeypatch: pytest.MonkeyPatch):
    # publish() shells out to `wrangler pages deploy` (see
    # app.publishing.cloudflare.engine) — these tests are about the HTTP
    # boundary, not wrangler's own wire behavior (see
    # test_cloudflare_pages_publisher.py), so it's mocked to a instant
    # success by default; tests that care about a wrangler failure
    # override this themselves.
    def fake_run(cmd, **kwargs):
        return _FakeCompletedProcess(returncode=0, stdout="Deployment complete", stderr="")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)


@pytest.fixture(autouse=True)
def _clear_publisher_override():
    yield
    app.dependency_overrides.pop(get_website_publisher, None)


class _FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _mock_cloudflare(handler) -> None:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.cloudflare.com/client/v4")
    client = CloudflarePagesClient("acct-1", API_TOKEN, http_client=http_client)
    app.dependency_overrides[get_website_publisher] = lambda: CloudflarePagesPublisher(
        client, account_id="acct-1", api_token=API_TOKEN
    )


def _successful_cloudflare_handler(deleted: list[str] | None = None):
    """A fresh, stateful handler per call: the project doesn't exist yet
    (first GET, before wrangler runs) but does by the time publish()
    checks status afterward (second GET) — and every GET after that, so
    a test that publishes and then deactivates the same handler
    instance sees the project as existing right up until DELETE
    actually removes it. `deleted`, if given, records every project
    name this handler received a successful DELETE for."""
    get_calls = {"n": 0}
    deleted_projects: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        project_name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "POST" and request.url.path.endswith("/pages/projects"):
            # A republish after a deactivate recreates the project under
            # the same name (ensure_project's own idempotent create) —
            # forget it was ever "deleted" so the next GET reports it
            # existing again, same as a real recreated Cloudflare project.
            created_name = json.loads(request.content or b"{}").get("name")
            if created_name:
                deleted_projects.discard(created_name)
            return httpx.Response(200, json={"success": True, "result": {"name": "site"}, "errors": []})
        if request.method == "DELETE":
            deleted_projects.add(project_name)
            if deleted is not None:
                deleted.append(project_name)
            return httpx.Response(200, json={"success": True, "result": {"id": project_name}, "errors": []})
        if request.method == "GET":
            if project_name in deleted_projects:
                return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
            get_calls["n"] += 1
            if get_calls["n"] == 1:
                return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {"name": "site", "latest_deployment": {"id": "dep-1"}},
                    "errors": [],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    return handler


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


def _publish(client: TestClient, business_id: str, tenant_id: uuid.UUID, site_config: dict = SITE_CONFIG):
    return client.post(
        f"/businesses/{business_id}/website/publish", json=site_config, headers={"X-Tenant-Id": str(tenant_id)}
    )


def _get_website(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.get(f"/businesses/{business_id}/website", headers={"X-Tenant-Id": str(tenant_id)})


def _deactivate_website(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(f"/businesses/{business_id}/website/deactivate", headers={"X-Tenant-Id": str(tenant_id)})


def test_publish_success_returns_a_provider_neutral_result_with_a_live_url(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "live"
    assert body["live_url"].startswith("https://site-")
    assert body["live_url"].endswith(".pages.dev/")
    assert body["deployment_id"] == f"site-{business['id'].replace('-', '')}::dep-1"
    assert API_TOKEN not in response.text


def test_missing_cloudflare_config_is_rejected(client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "website_publisher_not_configured"


def test_publish_failure_is_reported_and_reload_shows_failed(client: TestClient, tenant: Tenant):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        return httpx.Response(500, text="internal server error")

    _mock_cloudflare(handler)
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "website_publish_failed"

    state = _get_website(client, business["id"], tenant.id)
    assert state.status_code == 200
    assert state.json()["status"] == "failed"
    assert state.json()["live_url"] is None


def test_build_failure_is_reported_and_never_touches_the_provider(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    from app.publishing.build import SiteBuildError

    def _failing_build(site_config):
        raise SiteBuildError("astro build failed")

    monkeypatch.setattr("app.publishing.service.build_site", _failing_build)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Cloudflare when the build itself failed")

    _mock_cloudflare(handler)
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "website_publish_failed"


def test_invalid_site_config_payload_is_rejected(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id, site_config={"brand": {}, "seo": {}, "pages": []})

    assert response.status_code == 422


def test_get_website_returns_null_before_any_publish(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = _get_website(client, business["id"], tenant.id)

    assert response.status_code == 200
    assert response.json() is None


def test_get_website_reflects_persisted_state_after_reload(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)
    published = _publish(client, business["id"], tenant.id)

    reloaded = _get_website(client, business["id"], tenant.id)

    assert reloaded.status_code == 200
    body = reloaded.json()
    assert body["live_url"] == published.json()["live_url"]
    assert body["status"] == "live"


def test_publish_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, other_tenant.id)

    response = _publish(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_get_website_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, other_tenant.id)
    _publish(client, business["id"], other_tenant.id)

    response = _get_website(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_publish_requires_a_tenant_header(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)

    response = client.post(f"/businesses/{business['id']}/website/publish", json=SITE_CONFIG)

    assert response.status_code == 422


def test_publish_without_n8n_configured_succeeds_and_leaves_the_contact_form_without_an_action(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    # settings.n8n_base_url is None by default (no fixture here sets it)
    # — publishing a site with a lead-capture contact form must still
    # succeed; it just can't wire a real webhook URL, and must not fake
    # one (see app.publishing.service._inject_lead_capture_webhook_url).
    captured: list[dict] = []

    def _capturing_build(site_config):
        captured.append(site_config.model_dump(mode="json"))
        return WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})

    monkeypatch.setattr("app.publishing.service.build_site", _capturing_build)

    site_config_with_form = {
        **SITE_CONFIG,
        "pages": [
            {
                "path": "/",
                "blocks": [
                    {"type": "hero", "content": {"heading": "Tu reforma, sin sorpresas"}},
                    {
                        "type": "contact",
                        "content": {"heading": "Contacto", "form": {"fields": [{"name": "name", "label": "Nombre"}]}},
                    },
                ],
            }
        ],
    }

    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)

    response = _publish(client, business["id"], tenant.id, site_config=site_config_with_form)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "live"
    built_contact = next(b for p in captured[0]["pages"] for b in p["blocks"] if b["type"] == "contact")
    assert "action" not in built_contact["content"]["form"]


# --- deactivate (unpublish) -------------------------------------------------


def test_deactivate_success_takes_the_site_offline_and_clears_the_live_url(client: TestClient, tenant: Tenant):
    deleted: list[str] = []
    _mock_cloudflare(_successful_cloudflare_handler(deleted))
    business = _create_business(client, tenant.id)
    published = _publish(client, business["id"], tenant.id)
    assert published.status_code == 200, published.text

    response = _deactivate_website(client, business["id"], tenant.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "inactive"
    assert body["live_url"] is None
    assert deleted == [f"site-{business['id'].replace('-', '')}"]
    assert API_TOKEN not in response.text

    reloaded = _get_website(client, business["id"], tenant.id)
    assert reloaded.json()["status"] == "inactive"
    assert reloaded.json()["live_url"] is None


def test_deactivate_without_any_prior_publish_is_rejected(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)

    response = _deactivate_website(client, business["id"], tenant.id)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "website_not_published"


def test_deactivate_missing_cloudflare_config_is_rejected(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)

    # _mock_cloudflare registers a dependency_override for
    # get_website_publisher that ignores settings entirely — pop it so
    # this exercises the *real* get_website_publisher wiring against
    # the now-unconfigured settings, the same "no override registered"
    # pattern test_missing_cloudflare_config_is_rejected uses above.
    app.dependency_overrides.pop(get_website_publisher, None)
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)

    response = _deactivate_website(client, business["id"], tenant.id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "website_publisher_not_configured"


def test_deactivate_failure_is_reported_and_reload_still_shows_live(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)
    published = _publish(client, business["id"], tenant.id)
    assert published.status_code == 200, published.text

    def failing_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {"name": "site", "latest_deployment": {"id": "dep-1"}},
                    "errors": [],
                },
            )
        return httpx.Response(500, text="internal server error")

    _mock_cloudflare(failing_handler)

    response = _deactivate_website(client, business["id"], tenant.id)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "website_unpublish_failed"

    state = _get_website(client, business["id"], tenant.id)
    assert state.json()["status"] == "live"
    assert state.json()["live_url"] == published.json()["live_url"]


def test_deactivate_never_leaks_across_tenants(client: TestClient, tenant: Tenant, other_tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, other_tenant.id)
    _publish(client, business["id"], other_tenant.id)

    response = _deactivate_website(client, business["id"], tenant.id)

    assert response.status_code == 404


def test_deactivate_requires_a_tenant_header(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)

    response = client.post(f"/businesses/{business['id']}/website/deactivate")

    assert response.status_code == 422


def test_deactivate_is_idempotent_and_never_recalls_the_provider_when_already_inactive(
    client: TestClient, tenant: Tenant
):
    deleted: list[str] = []
    _mock_cloudflare(_successful_cloudflare_handler(deleted))
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)
    first = _deactivate_website(client, business["id"], tenant.id)
    assert first.status_code == 200, first.text
    deleted.clear()

    second = _deactivate_website(client, business["id"], tenant.id)

    assert second.status_code == 200, second.text
    assert second.json()["status"] == "inactive"
    assert deleted == []


def test_republish_after_deactivate_brings_the_site_back_live(client: TestClient, tenant: Tenant):
    _mock_cloudflare(_successful_cloudflare_handler())
    business = _create_business(client, tenant.id)
    _publish(client, business["id"], tenant.id)
    deactivated = _deactivate_website(client, business["id"], tenant.id)
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["status"] == "inactive"

    republished = _publish(client, business["id"], tenant.id)

    assert republished.status_code == 200, republished.text
    assert republished.json()["status"] == "live"
    assert republished.json()["live_url"] is not None
