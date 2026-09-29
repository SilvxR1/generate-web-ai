"""A8.3.4.2a — REAL DRAFT PREVIEW (backend).

Proves the stored WebsiteDraft artifact, the preview deployment and the
production deployment are byte-identical (`_headers` included) with ONE
build in total; the preview lifecycle (lazy, reused within 7 days,
redeployed from the same artifact after expiry, retired on publish); branch
and project safety of the preview publisher; tenant authorization of the
preview endpoint; and server-side suppression of preview leads/events.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.analytics_event import AnalyticsEvent
from app.db.models.business import Business
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.models.website_draft import WebsiteDraft
from app.dependencies import (
    get_optional_notification_sender,
    get_preview_publisher,
    get_private_artifact_storage,
    get_rate_limiter,
    get_session,
    get_website_publisher,
)
from app.domain.enums import WebsiteDraftStatus
from app.main import app
from app.publishing.artifact_store import artifact_sha256, pack_artifact
from app.publishing.cloudflare.engine import (
    PREVIEW_PROJECT_NAME,
    CloudflarePagesPreviewPublisher,
    preview_branch_for,
    validate_preview_branch,
)
from app.publishing.drafts import (
    PREVIEW_TTL,
    WebsiteDraftError,
    approve_website_draft,
    create_website_draft,
    ensure_draft_preview,
    publish_website_draft,
)
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import (
    PreviewDeployment,
    PreviewPublisher,
    PublishedSite,
    WebsiteArtifact,
    WebsitePublisher,
)
from app.schemas.site_config import SiteConfigPayload
from app.security.preview_origin import is_preview_origin
from app.security.rate_limit import InMemoryRateLimiter
from app.storage import LocalStorageProvider
from app.storage.private import PrivateArtifactStorage

_SITE_CONFIG = {
    "brand": {"name": "Reforma Casa Valencia"},
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
    "seo": {"title": "Reforma Casa Valencia", "description": "Reformas en Valencia."},
    "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {"heading": "Tu reforma"}}]}],
}
_HEADERS = b"/*\n  Content-Security-Policy: default-src 'self'; connect-src 'self' https://api.example.com\n"
PREVIEW_ORIGIN = f"https://1a2b3c4d.{PREVIEW_PROJECT_NAME}.pages.dev"


def _artifact() -> WebsiteArtifact:
    return WebsiteArtifact(
        files={
            "index.html": b"<html><body><form data-gwa-lead-form></form></body></html>",
            "_astro/app.Ab12.js": b"window.gwaAnalytics={};",
            "_astro/index.Cd34.css": b"body{color:#111}",
            "privacy/index.html": b"<html>privacy</html>",
            "images/logo.png": bytes(range(256)),
            "_headers": _HEADERS,
            "_redirects": b"/old /new 301\n",
        }
    )


def _completed(*args, **kwargs):
    return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()


class BuildCounter:
    def __init__(self) -> None:
        self.calls = 0
        self.produced: list[WebsiteArtifact] = []

    def __call__(self, site_config):
        self.calls += 1
        artifact = _artifact()
        self.produced.append(artifact)
        return artifact


class RecordingPreviewPublisher(PreviewPublisher):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deployed: list[tuple[str, WebsiteArtifact]] = []
        self.retired: list[tuple[str, str]] = []
        self.superseded: list[str] = []

    def publish_preview(self, *, branch, artifact):
        validate_preview_branch(branch)
        self.deployed.append((branch, artifact))
        if self.fail:
            raise WebsitePublisherError("simulated Pages failure")
        n = len(self.deployed)
        return PreviewDeployment(deployment_id=f"dep-{n}", url=f"https://{n:08x}.{PREVIEW_PROJECT_NAME}.pages.dev")

    def retire_preview(self, *, branch, deployment_id):
        self.retired.append((branch, deployment_id))

    def delete_superseded(self, deployment_id):
        self.superseded.append(deployment_id)


class RecordingPublisher(WebsitePublisher):
    def __init__(self) -> None:
        self.artifacts: list[WebsiteArtifact] = []

    def publish(self, *, site_id, artifact):
        self.artifacts.append(artifact)
        return PublishedSite(deployment_id="prod-1", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


@pytest.fixture()
def builds(monkeypatch: pytest.MonkeyPatch) -> BuildCounter:
    counter = BuildCounter()
    monkeypatch.setattr("app.publishing.drafts.build_site", counter)
    monkeypatch.setattr("app.publishing.service.build_site", counter)
    return counter


@pytest.fixture()
def storage(tmp_path: Path) -> PrivateArtifactStorage:
    return PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private"))


def _site_config() -> SiteConfigPayload:
    return SiteConfigPayload.model_validate(json.loads(json.dumps(_SITE_CONFIG)))


def _ready(session, tenant, business, storage) -> WebsiteDraft:
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        artifact_storage=storage,
    )
    session.flush()
    assert draft.status is WebsiteDraftStatus.READY
    return draft


def _preview(session, tenant, business, draft, storage, publisher, now=None):
    return ensure_draft_preview(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        draft_id=draft.id,
        artifact_storage=storage,
        preview_publisher=publisher,
        now=now,
    )


def _publish(session, tenant, business, draft, storage, preview_publisher, publisher=None):
    return publish_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        draft_id=draft.id,
        publisher=publisher or RecordingPublisher(),
        artifact_storage=storage,
        preview_publisher=preview_publisher,
    )


# --- 15. Byte identity: stored == preview == production, ONE build ------------


def test_stored_preview_and_production_artifacts_are_byte_identical_with_one_build(
    session: Session, tenant: Tenant, business: Business, storage, builds: BuildCounter
):
    draft = _ready(session, tenant, business, storage)
    preview_publisher = RecordingPreviewPublisher()
    _preview(session, tenant, business, draft, storage, preview_publisher)
    assert builds.calls == 1  # preview: zero builds

    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    production = RecordingPublisher()
    _publish(session, tenant, business, draft, storage, preview_publisher, production)
    assert builds.calls == 1  # production: zero builds — ONE build in total

    [validated] = builds.produced
    [(branch, previewed)] = preview_publisher.deployed
    [published] = production.artifacts
    assert branch == preview_branch_for(draft.id)
    assert set(previewed.files) == set(published.files) == set(validated.files)
    assert all(previewed.files[p] == published.files[p] == validated.files[p] for p in validated.files)
    assert previewed.files["_headers"] == published.files["_headers"] == _HEADERS
    assert artifact_sha256(previewed) == artifact_sha256(published) == draft.artifact_sha256
    # Changing only _headers still changes the semantic identity.
    tampered = WebsiteArtifact(files={**previewed.files, "_headers": _HEADERS + b"  X-Robots-Tag: noindex\n"})
    assert artifact_sha256(tampered) != draft.artifact_sha256


def test_real_cloudflare_preview_publisher_uploads_the_exact_bytes_to_the_preview_project_only(
    monkeypatch: pytest.MonkeyPatch,
):
    uploads: list[dict] = []
    deployments: list[dict] = [{"id": "placeholder", "deployment_trigger": {"metadata": {"branch": "production"}}}]

    class _Client:
        def ensure_project(self, project_name):
            assert project_name == PREVIEW_PROJECT_NAME

        def get_project(self, project_name):
            return {"canonical_deployment": {"id": "placeholder"}}

        def list_deployments(self, project_name):
            assert project_name == PREVIEW_PROJECT_NAME
            return list(reversed(deployments))

    def fake_run(args, **kwargs):
        project = next(a for a in args if a.startswith("--project-name=")).split("=", 1)[1]
        branch = next(a for a in args if a.startswith("--branch=")).split("=", 1)[1]
        directory = Path(args[args.index("deploy") + 1])
        files = {p.relative_to(directory).as_posix(): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        uploads.append({"project": project, "branch": branch, "files": files})
        deployments.append(
            {
                "id": f"cf-{len(uploads)}",
                "url": f"https://abcd{len(uploads):04d}.{PREVIEW_PROJECT_NAME}.pages.dev",
                "deployment_trigger": {"metadata": {"branch": branch}},
            }
        )
        return _completed()

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)
    publisher = CloudflarePagesPreviewPublisher(_Client(), account_id="acct", api_token="token")
    branch = preview_branch_for(uuid.uuid4())
    deployed = publisher.publish_preview(branch=branch, artifact=_artifact())

    [upload] = uploads
    assert upload["project"] == PREVIEW_PROJECT_NAME
    assert upload["branch"] == branch != "production"
    assert upload["files"] == _artifact().files  # byte-for-byte, _headers included, nothing injected
    assert deployed.deployment_id == "cf-1"
    assert str(deployed.url).startswith(f"https://abcd0001.{PREVIEW_PROJECT_NAME}.pages.dev")


def test_an_empty_preview_project_gets_only_a_placeholder_on_its_production_branch(monkeypatch: pytest.MonkeyPatch):
    uploads: list[tuple[str, dict]] = []
    deployments: list[dict] = []

    class _Client:
        def ensure_project(self, project_name):
            pass

        def get_project(self, project_name):
            return {}  # brand-new project: no deployment at all

        def list_deployments(self, project_name):
            return list(reversed(deployments))

    def fake_run(args, **kwargs):
        branch = next(a for a in args if a.startswith("--branch=")).split("=", 1)[1]
        directory = Path(args[args.index("deploy") + 1])
        uploads.append((branch, {p.name: p.read_bytes() for p in directory.rglob("*") if p.is_file()}))
        deployments.append(
            {
                "id": f"cf-{len(uploads)}",
                "url": f"https://h{len(uploads)}.{PREVIEW_PROJECT_NAME}.pages.dev",
                "deployment_trigger": {"metadata": {"branch": branch}},
            }
        )
        return _completed()

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)
    branch = preview_branch_for(uuid.uuid4())
    CloudflarePagesPreviewPublisher(_Client(), account_id="a", api_token="t").publish_preview(
        branch=branch, artifact=_artifact()
    )
    (first_branch, placeholder), (second_branch, customer) = uploads
    assert first_branch == "production" and set(placeholder) == {"index.html"}
    assert b"Nothing here" in placeholder["index.html"]
    assert second_branch == branch and customer["_headers"] == _HEADERS  # customer bytes only on the draft branch


# --- 3/4. Branch + project safety ---------------------------------------------


def test_preview_branch_is_deterministic_draft_derived_and_never_production():
    draft_id = uuid.uuid4()
    branch = preview_branch_for(draft_id)
    assert branch == preview_branch_for(draft_id)
    assert branch != preview_branch_for(uuid.uuid4())
    assert branch.startswith("d-") and len(branch) == 26
    assert validate_preview_branch(branch) == branch


@pytest.mark.parametrize(
    "bad", ["production", "main", "d-", "d-XYZ", "d-" + "0" * 23, "d-" + "0" * 25, "D-" + "0" * 24, "d-" + "g" * 24]
)
def test_preview_publisher_rejects_production_and_malformed_branches(bad: str):
    with pytest.raises(WebsitePublisherError):
        validate_preview_branch(bad)


def test_preview_publisher_refuses_production_business_projects():
    with pytest.raises(WebsitePublisherError):
        CloudflarePagesPreviewPublisher(object(), account_id="a", api_token="t", project_name="site-884eb764")


def test_preview_publisher_refuses_to_deploy_to_production_branch(monkeypatch: pytest.MonkeyPatch):
    def _never(*args, **kwargs):
        raise AssertionError("wrangler must not run")

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", _never)
    publisher = CloudflarePagesPreviewPublisher(object(), account_id="a", api_token="t")
    with pytest.raises(WebsitePublisherError):
        publisher.publish_preview(branch="production", artifact=_artifact())


@pytest.mark.parametrize(
    "deployments",
    [
        [],  # URL resolution failure: nothing for the branch
        [{"id": "d1", "url": "https://evil.example.com", "deployment_trigger": {"metadata": {"branch": "BRANCH"}}}],
        [
            {
                "id": "d1",
                "url": "http://x.gwa-draft-previews.pages.dev",
                "deployment_trigger": {"metadata": {"branch": "BRANCH"}},
            }
        ],
    ],
    ids=["no-deployment", "foreign-host", "not-https"],
)
def test_unresolvable_or_unexpected_preview_urls_are_never_reported(monkeypatch: pytest.MonkeyPatch, deployments):
    branch = preview_branch_for(uuid.uuid4())
    for d in deployments:
        d["deployment_trigger"]["metadata"]["branch"] = branch

    class _Client:
        def ensure_project(self, name):
            pass

        def get_project(self, name):
            return {"canonical_deployment": {"id": "x"}}

        def list_deployments(self, name):
            return deployments

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", _completed)
    publisher = CloudflarePagesPreviewPublisher(_Client(), account_id="a", api_token="t")
    with pytest.raises(WebsitePublisherError):
        publisher.publish_preview(branch=branch, artifact=_artifact())


def test_retire_supersedes_the_latest_preview_before_deleting_it(monkeypatch: pytest.MonkeyPatch):
    branch = preview_branch_for(uuid.uuid4())
    calls: list[str] = []

    class _Client:
        def list_deployments(self, name):
            return [{"id": "dep-live", "deployment_trigger": {"metadata": {"branch": branch}}}]

        def delete_deployment(self, name, deployment_id):
            assert name == PREVIEW_PROJECT_NAME
            calls.append(f"delete:{deployment_id}")

    def fake_run(args, **kwargs):
        directory = Path(args[args.index("deploy") + 1])
        assert b"Preview ended" in (directory / "index.html").read_bytes()
        calls.append(next(a for a in args if a.startswith("--branch=")))
        return _completed()

    monkeypatch.setattr("app.publishing.cloudflare.engine.subprocess.run", fake_run)
    CloudflarePagesPreviewPublisher(_Client(), account_id="a", api_token="t").retire_preview(
        branch=branch, deployment_id="dep-live"
    )
    assert calls == [f"--branch={branch}", "delete:dep-live"]


# --- 9/10. Lifecycle ------------------------------------------------------------


def test_preview_is_reused_within_ttl_and_redeployed_from_the_same_artifact_after_expiry(
    session: Session, tenant: Tenant, business: Business, storage, builds: BuildCounter
):
    draft = _ready(session, tenant, business, storage)
    publisher = RecordingPreviewPublisher()
    t0 = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)

    first = _preview(session, tenant, business, draft, storage, publisher, now=t0)
    again = _preview(session, tenant, business, draft, storage, publisher, now=t0 + timedelta(days=6))
    assert again == first  # double click / revisit: reused, no second deployment
    assert len(publisher.deployed) == 1
    assert first.expires_at == t0 + PREVIEW_TTL == t0 + timedelta(days=7)

    renewed = _preview(session, tenant, business, draft, storage, publisher, now=t0 + timedelta(days=7))
    assert len(publisher.deployed) == 2
    assert renewed.preview_url != first.preview_url
    assert publisher.deployed[0][1].files == publisher.deployed[1][1].files  # same stored artifact
    assert publisher.superseded == ["dep-1"]
    assert builds.calls == 1
    assert draft.status is WebsiteDraftStatus.READY  # preview never approves


def test_approved_drafts_can_be_previewed(session, tenant, business, storage, builds):
    draft = _ready(session, tenant, business, storage)
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    _preview(session, tenant, business, draft, storage, RecordingPreviewPublisher())
    assert draft.status is WebsiteDraftStatus.APPROVED


def test_publish_retires_the_preview_and_clears_its_metadata(session, tenant, business, storage, builds):
    draft = _ready(session, tenant, business, storage)
    preview_publisher = RecordingPreviewPublisher()
    _preview(session, tenant, business, draft, storage, preview_publisher)
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    _publish(session, tenant, business, draft, storage, preview_publisher)

    assert preview_publisher.retired == [(preview_branch_for(draft.id), "dep-1")]
    assert draft.preview_url is None and draft.preview_deployment_id is None
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, preview_publisher)
    assert exc.value.code == "website_draft_not_previewable"  # published: already live


def test_retire_failure_never_fails_a_successful_publish(session, tenant, business, storage, builds):
    class _Broken(RecordingPreviewPublisher):
        def retire_preview(self, *, branch, deployment_id):
            raise WebsitePublisherError("pages down")

    publisher = _Broken()
    draft = _ready(session, tenant, business, storage)
    _preview(session, tenant, business, draft, storage, publisher)
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    result = _publish(session, tenant, business, draft, storage, publisher)
    assert result.status.value == "live"
    assert draft.status is WebsiteDraftStatus.PUBLISHED


# --- 16. Failure modes --------------------------------------------------------


def _assert_no_preview(draft: WebsiteDraft, publisher: RecordingPreviewPublisher, *, deployed: int = 0):
    assert draft.preview_url is None and draft.preview_deployment_id is None and draft.preview_created_at is None
    assert len(publisher.deployed) == deployed


def test_build_failed_draft_is_not_previewable(session, tenant, business, storage, monkeypatch):
    def _fail(site_config):
        raise WebsitePublisherError("astro build failed")

    monkeypatch.setattr("app.publishing.drafts.build_site", _fail)
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        artifact_storage=storage,
    )
    publisher = RecordingPreviewPublisher()
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, publisher)
    assert exc.value.code == "website_draft_not_previewable"
    _assert_no_preview(draft, publisher)


def test_legacy_draft_without_artifact_is_refused(session, tenant, business, storage):
    legacy = WebsiteDraft(
        tenant_id=tenant.id, business_id=business.id, site_config=_SITE_CONFIG, status=WebsiteDraftStatus.READY
    )
    session.add(legacy)
    session.flush()
    publisher = RecordingPreviewPublisher()
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, legacy, storage, publisher)
    assert exc.value.code == "website_draft_artifact_missing"
    _assert_no_preview(legacy, publisher)


def test_missing_private_artifact_fails_closed(session, tenant, business, storage, builds):
    draft = _ready(session, tenant, business, storage)
    storage.delete(draft.artifact_key)
    publisher = RecordingPreviewPublisher()
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, publisher)
    assert exc.value.code == "website_draft_artifact_unavailable"
    _assert_no_preview(draft, publisher)


def test_hash_mismatch_fails_closed(session, tenant, business, storage, builds):
    draft = _ready(session, tenant, business, storage)
    tampered = _artifact()
    tampered.files["_headers"] = b"/*\n  Content-Security-Policy: default-src *\n"
    storage._backend._resolve(draft.artifact_key).write_bytes(pack_artifact(tampered))
    publisher = RecordingPreviewPublisher()
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, publisher)
    assert exc.value.code == "website_draft_artifact_integrity_failed"
    _assert_no_preview(draft, publisher)


def test_provider_failure_or_timeout_leaves_no_metadata_and_production_untouched(
    session, tenant, business, storage, builds
):
    from app.publishing.service import get_website_state

    draft = _ready(session, tenant, business, storage)
    publisher = RecordingPreviewPublisher(fail=True)  # wrangler failures and timeouts both surface this way
    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, publisher)
    assert exc.value.code == "website_draft_preview_failed"
    assert exc.value.status_code == 502
    _assert_no_preview(draft, publisher, deployed=1)
    assert get_website_state(session=session, tenant_id=tenant.id, business_id=business.id) is None


# --- 11. API ------------------------------------------------------------------


@pytest.fixture()
def client(session, storage, builds):
    preview_publisher = RecordingPreviewPublisher()

    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_private_artifact_storage] = lambda: storage
    app.dependency_overrides[get_preview_publisher] = lambda: preview_publisher
    app.dependency_overrides[get_website_publisher] = lambda: RecordingPublisher()
    test_client = TestClient(app)
    test_client.preview_publisher = preview_publisher  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        for dep in (get_session, get_private_artifact_storage, get_preview_publisher, get_website_publisher):
            app.dependency_overrides.pop(dep, None)


def _api_draft(client: TestClient, tenant: Tenant, business: Business) -> dict:
    response = client.post(
        f"/businesses/{business.id}/website-drafts",
        json={"site_config": _SITE_CONFIG},
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_preview_endpoint_returns_only_safe_metadata(client: TestClient, tenant: Tenant, business: Business):
    draft = _api_draft(client, tenant, business)
    url = f"/businesses/{business.id}/website-drafts/{draft['id']}/preview"
    response = client.post(url, headers={"X-Tenant-Id": str(tenant.id)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"preview_url", "created_at", "expires_at"}
    assert f".{PREVIEW_PROJECT_NAME}.pages.dev" in body["preview_url"]
    for forbidden in ("website-drafts/", "artifact", "r2.dev", "cloudflarestorage", "dep-1"):
        assert forbidden not in response.text
    again = client.post(url, headers={"X-Tenant-Id": str(tenant.id)})
    assert again.json() == body
    assert len(client.preview_publisher.deployed) == 1


def test_preview_endpoint_denies_other_tenants_and_wrong_business(
    client: TestClient, session: Session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    draft = _api_draft(client, tenant, business)
    url = f"/businesses/{business.id}/website-drafts/{draft['id']}/preview"
    assert client.post(url, headers={"X-Tenant-Id": str(other_tenant.id)}).status_code == 404

    other_business = Business(
        tenant_id=tenant.id, name="Otra", slug="otra", vertical="other", raw_description="Otra empresa de prueba."
    )
    session.add(other_business)
    session.flush()
    wrong = f"/businesses/{other_business.id}/website-drafts/{draft['id']}/preview"
    assert client.post(wrong, headers={"X-Tenant-Id": str(tenant.id)}).status_code == 404
    assert client.preview_publisher.deployed == []


def test_preview_endpoint_is_503_when_previews_are_not_configured(
    client: TestClient, tenant: Tenant, business: Business, monkeypatch
):
    from app.config import settings

    app.dependency_overrides.pop(get_preview_publisher, None)
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)
    draft = _api_draft(client, tenant, business)
    response = client.post(
        f"/businesses/{business.id}/website-drafts/{draft['id']}/preview", headers={"X-Tenant-Id": str(tenant.id)}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "preview_publisher_not_configured"


# --- 12. Origin detection -----------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (f"https://{PREVIEW_PROJECT_NAME}.pages.dev", True),
        (f"https://1a2b3c4d.{PREVIEW_PROJECT_NAME}.pages.dev", True),
        (f"https://d-0123456789abcdef01234567.{PREVIEW_PROJECT_NAME}.pages.dev", True),
        (f"https://1A2B.{PREVIEW_PROJECT_NAME.upper()}.PAGES.DEV", True),
        (f"https://1a2b3c4d.{PREVIEW_PROJECT_NAME}.pages.dev:443", True),
        (f"https://{PREVIEW_PROJECT_NAME}.pages.dev.attacker.com", False),
        (f"https://evil-{PREVIEW_PROJECT_NAME}.pages.dev.attacker.com", False),
        (f"https://evil-{PREVIEW_PROJECT_NAME}.pages.dev", False),
        (f"https://x{PREVIEW_PROJECT_NAME}.pages.dev", False),
        (f"http://1a2b.{PREVIEW_PROJECT_NAME}.pages.dev", False),
        (f"https://user@1a2b.{PREVIEW_PROJECT_NAME}.pages.dev", False),
        (f"https://1a2b.{PREVIEW_PROJECT_NAME}.pages.dev:notaport", False),
        (f"https://1a2b.{PREVIEW_PROJECT_NAME}.pages.dev/path", False),
        ("https://site-884eb76424494bbea6449d8d937f7a9d.pages.dev", False),
        ("https://cositasypuntos.com", False),
        ("https://www.cositasypuntos.com", False),
        ("null", False),
        ("", False),
        (None, False),
    ],
)
def test_is_preview_origin(origin, expected):
    assert is_preview_origin(origin) is expected


# --- 13/14. Lead + event suppression ------------------------------------------


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list = []

    def send(self, email):
        self.sent.append(email)


@pytest.fixture()
def public_client(session):
    sender = RecordingSender()

    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    app.dependency_overrides[get_optional_notification_sender] = lambda: sender
    test_client = TestClient(app)
    test_client.sender = sender  # type: ignore[attr-defined]
    try:
        yield test_client
    finally:
        for dep in (get_session, get_rate_limiter, get_optional_notification_sender):
            app.dependency_overrides.pop(dep, None)


def _lead_payload() -> dict:
    return {
        "name": "Maria Garcia",
        "email": "maria@example.com",
        "message": "Necesito un presupuesto.",
        "consent": True,
        "rendered_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    }


def _counts(session: Session, business: Business) -> tuple[int, int, int]:
    session.flush()
    return (
        session.query(Lead).filter_by(business_id=business.id).count(),
        session.query(InternalNotification).filter_by(business_id=business.id).count(),
        session.query(AnalyticsEvent).filter_by(business_id=business.id).count(),
    )


def test_preview_lead_is_suppressed_with_a_success_compatible_response(
    public_client: TestClient, session: Session, business: Business, caplog, monkeypatch
):
    production = public_client.post(f"/public/businesses/{business.id}/leads", json=_lead_payload())
    before = _counts(session, business)
    sent_before = len(public_client.sender.sent)
    monkeypatch.setattr(
        "app.routers.public._dispatch_to_automation_if_configured",
        lambda session, lead: pytest.fail("n8n dispatch must not run for a preview lead"),
    )
    monkeypatch.setattr(
        "app.routers.public.deliver_internal_notification",
        lambda **kwargs: pytest.fail("no notification may be delivered for a preview lead"),
    )
    caplog.set_level("INFO")

    response = public_client.post(
        f"/public/businesses/{business.id}/leads", json=_lead_payload(), headers={"Origin": PREVIEW_ORIGIN}
    )

    assert response.status_code == production.status_code == 201
    assert response.json() == production.json()  # identical frontend contract
    assert _counts(session, business) == before  # zero Lead, zero InternalNotification, zero events
    assert len(public_client.sender.sent) == sent_before  # zero email
    assert "public_lead_suppressed_preview" in caplog.text
    assert "maria" not in caplog.text.lower() and "presupuesto" not in caplog.text.lower()  # no PII


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "https://cositasypuntos.com",
        "https://site-884eb76424494bbea6449d8d937f7a9d.pages.dev",
        f"https://{PREVIEW_PROJECT_NAME}.pages.dev.attacker.com",
    ],
)
def test_production_and_lookalike_origins_keep_creating_leads(
    public_client: TestClient, session: Session, business: Business, origin
):
    headers = {"Origin": origin} if origin else {}
    before = _counts(session, business)
    response = public_client.post(f"/public/businesses/{business.id}/leads", json=_lead_payload(), headers=headers)
    assert response.status_code == 201
    after = _counts(session, business)
    assert after[0] == before[0] + 1 and after[1] == before[1] + 1


def test_preview_lead_keeps_existing_validation_contract(public_client: TestClient, business: Business):
    bad = {**_lead_payload(), "email": None}
    response = public_client.post(
        f"/public/businesses/{business.id}/leads", json=bad, headers={"Origin": PREVIEW_ORIGIN}
    )
    assert response.status_code == 422


def test_preview_event_is_suppressed_and_production_event_recorded(
    public_client: TestClient, session: Session, business: Business, caplog
):
    caplog.set_level("INFO")
    payload = {"event_type": "page_view", "source_page": "/"}
    suppressed = public_client.post(
        f"/public/businesses/{business.id}/events", json=payload, headers={"Origin": PREVIEW_ORIGIN}
    )
    assert suppressed.status_code == 201
    assert suppressed.json() == {"received": True}
    assert _counts(session, business)[2] == 0
    assert "public_event_suppressed_preview" in caplog.text

    recorded = public_client.post(
        f"/public/businesses/{business.id}/events", json=payload, headers={"Origin": "https://cositasypuntos.com"}
    )
    assert recorded.status_code == 201
    assert _counts(session, business)[2] == 1


# --- 8. Migration -------------------------------------------------------------


def test_preview_migration_is_additive_reversible_and_the_single_head(tmp_path: Path):
    import os
    import subprocess
    import sys

    import sqlalchemy as sa

    api_root = Path(__file__).resolve().parents[1]

    def alembic(*args: str) -> str:
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'm.db'}"}
        done = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=api_root, env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def columns() -> dict:
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
        try:
            return {c["name"]: c for c in sa.inspect(engine).get_columns("website_drafts")}
        finally:
            engine.dispose()

    alembic("upgrade", "d5e8f3a1b2c4")
    assert "preview_url" not in columns()
    alembic("upgrade", "e6f9a2b3c4d5")
    cols = columns()
    for name in ("preview_deployment_id", "preview_url", "preview_created_at"):
        assert cols[name]["nullable"] is True
    alembic("downgrade", "d5e8f3a1b2c4")
    assert "preview_deployment_id" not in columns()
    alembic("upgrade", "head")
    assert "preview_created_at" in columns()
    heads = alembic("heads").split()
    assert heads.count("(head)") == 1  # still a single head (later revisions build on this one)
