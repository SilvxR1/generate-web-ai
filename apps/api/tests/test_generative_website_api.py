"""HTTP-level tests for the P2 generative workflow endpoints
(app.routers.creative): create -> critic-selected -> develop ->
generative website-draft -> approve -> publish (single endpoint,
branching by engine), and that the deterministic lifecycle is completely
unaffected. FrontendEngineer/HiggsfieldCreativeDirector are both faked
here (no real network/credit spend) — real-provider coverage lives in
tests/test_frontend_engine_real.py and test_higgsfield_cli_director.py.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.creative.director import CreativeDirectorProvider
from app.creative.frontend_engine.engine import FrontendEngineer, FrontendEngineResult
from app.db.models.tenant import Tenant
from app.dependencies import (
    get_creative_director,
    get_frontend_engineer,
    get_session,
    get_storage_provider,
    get_website_publisher,
)
from app.domain.business_config.examples import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import CreativeProviderName
from app.main import app
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.storage.provider import StorageProvider, StoredFile


class _FakeDirector(CreativeDirectorProvider):
    name = CreativeProviderName.INTERNAL

    def create_directions(self, brief, assets, budget):
        return [
            CreativeDirection(
                concept=CreativeConcept(name="Test direction", rationale="r", narrative="n"),
                visual_language=VisualLanguage(
                    mood="m",
                    palette_direction="p",
                    typography_direction="t",
                    composition_philosophy="c",
                    imagery_treatment="i",
                    graphic_language="g",
                ),
                experience=ExperienceDirection(
                    navigation_concept="n", storytelling_model="s", responsive_adaptation="r"
                ),
                content_strategy=ContentStrategy(
                    hierarchy="h", primary_user_journey="j", conversion_strategy="lead_capture"
                ),
            )
        ]

    def develop_direction(self, selected, brief, assets, budget):
        developed = selected.model_copy(deep=True)
        developed.generation_metadata["stage"] = "developed"
        return developed


class _FakeFrontendEngineer(FrontendEngineer):
    name = "fake"

    def generate(
        self,
        *,
        business_config,
        creative_direction,
        assets,
        platform_contract_version,
        business_id,
        api_base_url=None,
    ):
        html = (
            '<html><head><title>T</title><meta name="description" content="d">'
            '<meta name="viewport" content="width=device-width">'
            f'<script type="application/json" id="platform-config">{{"businessId": "{business_id}"}}</script>'
            "</head><body><form data-gwa-lead-form></form>"
            "<script>submitLead();window.gwaConsent={};window.gwaAnalytics={};</script>"
            "</body></html>"
        )
        legal = '<html><head><title>L</title><meta name="description" content="d"></head><body>l</body></html>'
        return FrontendEngineResult(
            artifact=WebsiteArtifact(
                files={
                    "index.html": html.encode(),
                    "privacy/index.html": legal.encode(),
                    "terms/index.html": legal.encode(),
                    "cookies/index.html": legal.encode(),
                }
            ),
            workspace_key=f"{business_id}/fake-source.tar.gz",
            build_command="fake",
            output_dir="dist",
            dependencies=[],
            generator_provider="fake",
            generator_model=None,
            duration_ms=1,
        )


class _FakeStorage(StorageProvider):
    def save(self, *, storage_key, content):
        return StoredFile(storage_key=storage_key)

    def delete(self, storage_key):
        pass

    def url_path(self, storage_key):
        return f"/uploads/{storage_key}"

    def load(self, storage_key):
        return b"fake-archive-bytes"


class _FakePublisher(WebsitePublisher):
    def publish(self, *, site_id, artifact):
        return PublishedSite(deployment_id="dep-gen-1", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    # The generative publish path rebuilds from the archive for real
    # (app.creative.frontend_engine.build.rebuild_from_archive) — faked
    # here since _FakeStorage.load returns non-real archive bytes; this
    # test is about the HTTP/lifecycle wiring, not the build itself
    # (covered for real elsewhere).
    monkeypatch.setattr(
        "app.publishing.service.rebuild_from_archive",
        lambda archive, **kwargs: WebsiteArtifact(files={"index.html": b"<html></html>"}),
    )

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_website_publisher] = lambda: _FakePublisher()
    app.dependency_overrides[get_storage_provider] = lambda: _FakeStorage()
    app.dependency_overrides[get_creative_director] = lambda: _FakeDirector()
    app.dependency_overrides[get_frontend_engineer] = lambda: _FakeFrontendEngineer()
    try:
        yield TestClient(app)
    finally:
        deps = (get_session, get_website_publisher, get_storage_provider, get_creative_director, get_frontend_engineer)
        for dep in deps:
            app.dependency_overrides.pop(dep, None)


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


@pytest.fixture()
def business_with_config(business, session):
    business.config = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json")
    session.flush()
    return business


def test_create_directions_persists_and_returns_a_recommended_candidate(
    client: TestClient, tenant: Tenant, business_with_config
):
    response = client.post(
        f"/businesses/{business_with_config.id}/creative-directions", json={}, headers=_headers(tenant.id)
    )

    assert response.status_code == 201, response.text
    directions = response.json()
    assert len(directions) == 1
    assert directions[0]["is_recommended"] is True
    assert directions[0]["concept"]["name"] == "Test direction"


def test_develop_direction_deepens_the_same_row(client: TestClient, tenant: Tenant, business_with_config):
    [direction] = client.post(
        f"/businesses/{business_with_config.id}/creative-directions", json={}, headers=_headers(tenant.id)
    ).json()

    response = client.post(
        f"/businesses/{business_with_config.id}/creative-directions/{direction['id']}/develop",
        json={},
        headers=_headers(tenant.id),
    )

    assert response.status_code == 200, response.text
    assert response.json()["generation_metadata"]["stage"] == "developed"
    assert response.json()["id"] == direction["id"]  # same row, not a new one


def test_full_generative_lifecycle_create_approve_publish(client: TestClient, tenant: Tenant, business_with_config):
    [direction] = client.post(
        f"/businesses/{business_with_config.id}/creative-directions", json={}, headers=_headers(tenant.id)
    ).json()

    draft_response = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/generative",
        json={"creative_direction_id": direction["id"]},
        headers=_headers(tenant.id),
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()
    assert draft["status"] == "ready"  # PlatformContract passed against the fake engine's compliant output
    assert draft["site_config"] is None

    approved = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/{draft['id']}/approve", headers=_headers(tenant.id)
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    published = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/{draft['id']}/publish", headers=_headers(tenant.id)
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "live"


def test_generative_frontend_engineer_unavailable_returns_503(
    client: TestClient, tenant: Tenant, business_with_config
):
    """P2.14: a genuinely unconfigured engine fails loudly — never a
    silent deterministic substitution."""
    from app.dependencies import get_frontend_engineer as real_dep
    from app.errors import AppError

    def _raise_unconfigured():
        raise AppError(
            "The AI Frontend Engineer is not configured on this server.",
            code="frontend_engineer_not_configured",
            status_code=503,
        )

    app.dependency_overrides[real_dep] = _raise_unconfigured
    response = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/generative",
        json={"creative_direction_id": str(uuid.uuid4())},
        headers=_headers(tenant.id),
    )
    assert response.status_code == 503


def test_visual_qa_endpoint_runs_a_real_browser_pass_and_persists_results(
    client: TestClient, tenant: Tenant, business_with_config, monkeypatch: pytest.MonkeyPatch
):
    """P2 continuation Part 4/5: POST .../visual-qa runs a real headless
    browser against the draft's real build output (Chromium is real
    here — only the archive rebuild is faked, since _FakeStorage.load
    returns non-real archive bytes) and GET .../generative-artifact then
    reports it, never a fabricated pass."""
    real_html = (
        "<html><head><title>T</title><meta name=\"description\" content=\"d\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        "<body><h1>Visual QA Co</h1><p>Real content.</p></body></html>"
    )
    monkeypatch.setattr(
        "app.publishing.drafts.rebuild_from_archive",
        lambda archive, **kwargs: WebsiteArtifact(files={"index.html": real_html.encode()}),
    )

    [direction] = client.post(
        f"/businesses/{business_with_config.id}/creative-directions", json={}, headers=_headers(tenant.id)
    ).json()
    draft = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/generative",
        json={"creative_direction_id": direction["id"]},
        headers=_headers(tenant.id),
    ).json()
    assert draft["status"] == "ready"

    before = client.get(
        f"/businesses/{business_with_config.id}/website-drafts/{draft['id']}/generative-artifact",
        headers=_headers(tenant.id),
    )
    assert before.status_code == 200, before.text
    assert before.json()["visual_qa_state"] == {}
    assert before.json()["screenshot_keys"] == {}

    qa_response = client.post(
        f"/businesses/{business_with_config.id}/website-drafts/{draft['id']}/visual-qa",
        headers=_headers(tenant.id),
    )
    assert qa_response.status_code == 200, qa_response.text
    body = qa_response.json()
    assert body["visual_qa_state"]["passed"] is True
    assert set(body["screenshot_keys"]) == {"desktop", "tablet", "mobile"}
    # Real, servable URLs Studio's PREVIEW_READY state renders — resolved
    # from StorageProvider.url_path, never a raw internal storage key.
    assert set(body["screenshot_urls"]) == {"desktop", "tablet", "mobile"}
    for viewport, storage_key in body["screenshot_keys"].items():
        assert body["screenshot_urls"][viewport] == f"/uploads/{storage_key}"

    after = client.get(
        f"/businesses/{business_with_config.id}/website-drafts/{draft['id']}/generative-artifact",
        headers=_headers(tenant.id),
    )
    assert after.json()["visual_qa_state"]["passed"] is True
    assert set(after.json()["screenshot_urls"]) == {"desktop", "tablet", "mobile"}
