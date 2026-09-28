"""HTTP-level tests for the P2 generative workflow endpoints
(app.routers.creative): create -> critic-selected -> develop ->
generative website-draft -> approve -> publish (single endpoint,
branching by engine), and that the deterministic lifecycle is completely
unaffected. FrontendEngineer/HiggsfieldCreativeDirector are both faked
here (no real network/credit spend) — real-provider coverage lives in
tests/test_frontend_engine_real.py and test_higgsfield_cli_director.py.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.creative.director import CreativeDirectorProvider
from app.creative.frontend_engine.engine import FrontendEngineer, FrontendEngineResult
from app.db.models.tenant import Tenant
from app.dependencies import (
    get_creative_director,
    get_frontend_engineer,
    get_private_artifact_storage,
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
from app.storage.private import PrivateArtifactStorage
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


@pytest.fixture(autouse=True)
def _public_api_origin(monkeypatch: pytest.MonkeyPatch):
    # A8.3.4-P0: generated sites must render a usable https API origin (the
    # TestClient's own http://testserver isn't one); production sets this
    # via INTERNAL_API_BASE_URL.
    from app.config import settings

    monkeypatch.setattr(settings, "internal_api_base_url", "https://api.example.com")


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
            # Same shape the real engine injects (frontend_engine.build._inject_platform_config).
            '<script type="application/json" id="platform-config">'
            + json.dumps({"businessId": business_id, "apiBaseUrl": api_base_url})
            + "</script>"
            "</head><body><h1>Generative Co</h1><p>Real content.</p><form data-gwa-lead-form></form>"
            # Defines (never calls an undefined) submitLead, so a real
            # browser Visual QA pass over this exact stored artifact
            # sees no page errors.
            "<script>function submitLead(){}window.gwaConsent={};window.gwaAnalytics={};</script>"
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
    """In-memory: A8.3.4.1 stores each draft's validated artifact and
    publish loads it back, so saved bytes must really round-trip."""

    provider_name = "fake"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def save(self, *, storage_key, content, content_type=None):
        self.objects[storage_key] = content
        return StoredFile(storage_key=storage_key)

    def delete(self, storage_key):
        self.objects.pop(storage_key, None)

    def exists(self, storage_key):
        return storage_key in self.objects

    def presigned_url(self, storage_key, *, expires_in_seconds):
        return None

    def url_path(self, storage_key):
        return f"/uploads/{storage_key}"

    def load(self, storage_key):
        return self.objects[storage_key]


class _FakePublisher(WebsitePublisher):
    published_artifacts: list[WebsiteArtifact] = []

    def publish(self, *, site_id, artifact):
        self.published_artifacts.append(artifact)
        return PublishedSite(deployment_id="dep-gen-1", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    # A8.3.4.1: neither publish nor Visual QA may rebuild an
    # artifact-backed draft — any call here fails the test loudly.
    def _no_rebuild(*args, **kwargs):
        raise AssertionError("an artifact-backed generative draft must never be rebuilt")

    monkeypatch.setattr("app.publishing.drafts.rebuild_from_archive", _no_rebuild)

    # A8.3.4.1b: two DIFFERENT stores — public assets/screenshots vs the
    # private draft-artifact bucket — so tests can prove which one got what.
    storage = _FakeStorage()
    private = _FakeStorage()
    _FakePublisher.published_artifacts = []
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_website_publisher] = lambda: _FakePublisher()
    app.dependency_overrides[get_storage_provider] = lambda: storage
    app.dependency_overrides[get_private_artifact_storage] = lambda: PrivateArtifactStorage(private)
    app.dependency_overrides[get_creative_director] = lambda: _FakeDirector()
    app.dependency_overrides[get_frontend_engineer] = lambda: _FakeFrontendEngineer()
    test_client = TestClient(app)
    test_client.public_storage = storage  # type: ignore[attr-defined]
    test_client.private_storage = private  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        deps = (
            get_session,
            get_website_publisher,
            get_storage_provider,
            get_private_artifact_storage,
            get_creative_director,
            get_frontend_engineer,
        )
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

    # A8.3.4.1: the published bytes are exactly the engine's validated
    # build output (platform config included) — not a rebuild.
    expected = _FakeFrontendEngineer().generate(
        business_config=None,
        creative_direction=None,
        assets=(),
        platform_contract_version="",
        business_id=str(business_with_config.id),
        api_base_url="https://api.example.com",  # settings.internal_api_base_url, set above
    ).artifact
    [deployed] = _FakePublisher.published_artifacts
    assert deployed.files == expected.files

    # A8.3.4.1b: the artifact lives ONLY in private storage.
    assert [k for k in client.private_storage.objects if k.startswith("website-drafts/")]
    assert not [k for k in client.public_storage.objects if k.startswith("website-drafts/")]


def test_generative_frontend_engineer_unavailable_returns_503(client: TestClient, tenant: Tenant, business_with_config):
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
    here; A8.3.4.1: the output is the draft's stored, validated artifact
    — never a rebuild) and GET .../generative-artifact then reports it,
    never a fabricated pass."""

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
