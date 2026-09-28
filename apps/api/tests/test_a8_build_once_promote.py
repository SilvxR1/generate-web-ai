"""A8.3.4.1 — BUILD ONCE / PROMOTE.

Proves that a WebsiteDraft is built exactly once and that Publish deploys
the exact validated bytes (every file, `_headers` included) — never a
rebuild — plus the canonical hash, archive safety, failure ordering,
immutability, legacy-draft refusal and WebsiteVersion traceability.

build_site is faked (instant, deterministic) exactly like
test_website_draft_service.py; the real-`astro build` equivalent of the
byte-equality proof lives in test_website_draft_real_build.py.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.db.models.website_draft import WebsiteDraft
from app.db.models.website_version import WebsiteVersion
from app.dependencies import get_session, get_storage_provider, get_website_publisher
from app.domain.enums import DeployTarget, WebsiteDraftStatus, WebsiteStatus
from app.main import app
from app.publishing.artifact_store import (
    ArtifactAlreadyExistsError,
    ArtifactArchiveCorruptError,
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactUnavailableError,
    artifact_sha256,
    draft_artifact_storage_key,
    load_draft_artifact,
    pack_artifact,
    store_draft_artifact,
    unpack_artifact,
)
from app.publishing.drafts import (
    WebsiteDraftError,
    approve_website_draft,
    create_website_draft,
    publish_website_draft,
)
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.publishing.service import WebsitePublishError
from app.publishing.versions import rollback_to_version
from app.repositories.website_version import WebsiteVersionRepository
from app.schemas.site_config import SiteConfigPayload
from app.storage import LocalStorageProvider
from app.storage.errors import StorageProviderError

API_ROOT = Path(__file__).resolve().parents[1]
NEW_REVISION = "d5e8f3a1b2c4"
PREVIOUS_REVISION = "c4d7e2a9f1b3"

_SITE_CONFIG = {
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

_HEADERS = (
    b"/*\n  Content-Security-Policy: default-src 'self'; connect-src 'self' https://api.example.com\n"
    b"  X-Frame-Options: DENY\n"
)


def _site_artifact() -> WebsiteArtifact:
    """Shaped like a real build: HTML, hashed CSS/JS, an asset, legal
    pages and the runtime/security files that are part of identity."""
    return WebsiteArtifact(
        files={
            "index.html": b"<html><head><script src='/_astro/app.Ab12.js'></script></head><body>Hola</body></html>",
            "_astro/index.Cd34.css": b"body{color:#111827}",
            "_astro/app.Ab12.js": b"window.gwaAnalytics={};",
            "images/logo.png": bytes(range(256)),
            "privacy/index.html": b"<html>privacy</html>",
            "terms/index.html": b"<html>terms</html>",
            "_headers": _HEADERS,
            "_redirects": b"/old /new 301\n",
        }
    )


def _site_config() -> SiteConfigPayload:
    return SiteConfigPayload.model_validate(json.loads(json.dumps(_SITE_CONFIG)))


class RecordingPublisher(WebsitePublisher):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.artifacts: list[WebsiteArtifact] = []

    def publish(self, *, site_id, artifact):
        self.artifacts.append(artifact)
        if self.fail:
            raise WebsitePublisherError("simulated hosting provider failure")
        return PublishedSite(deployment_id=f"dep-{len(self.artifacts)}", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


class BuildCounter:
    """Stands in for build_site everywhere it can be reached from — the
    draft module AND the publish service — so any rebuild is counted."""

    def __init__(self) -> None:
        self.calls = 0
        self.produced: list[WebsiteArtifact] = []

    def __call__(self, site_config: SiteConfigPayload) -> WebsiteArtifact:
        self.calls += 1
        artifact = _site_artifact()
        self.produced.append(artifact)
        return artifact


@pytest.fixture()
def storage(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(root_dir=tmp_path / "storage")


@pytest.fixture()
def builds(monkeypatch: pytest.MonkeyPatch) -> BuildCounter:
    counter = BuildCounter()
    monkeypatch.setattr("app.publishing.drafts.build_site", counter)
    monkeypatch.setattr("app.publishing.service.build_site", counter)
    return counter


def _stored_archives(storage: LocalStorageProvider) -> list[Path]:
    return list(storage._root_dir.rglob("*.gz"))


def _create(session, tenant, business, storage) -> WebsiteDraft:
    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config(), storage=storage
    )
    session.flush()
    return draft


def _create_and_approve(session, tenant, business, storage) -> WebsiteDraft:
    draft = _create(session, tenant, business, storage)
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    session.flush()
    return draft


def _publish(session, tenant, business, draft, publisher, storage):
    return publish_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        draft_id=draft.id,
        publisher=publisher,
        storage=storage,
    )


def _live_website(session: Session, tenant: Tenant, business: Business) -> Website:
    website = Website(
        tenant_id=tenant.id,
        business_id=business.id,
        deploy_target=DeployTarget.CLOUDFLARE,
        status=WebsiteStatus.LIVE,
        deploy_url="https://live-before.pages.dev",
        provider_deployment_id="dep-live-before",
        config={"previous": True},
    )
    session.add(website)
    session.flush()
    return website


def _versions(session, tenant, business) -> list[WebsiteVersion]:
    return WebsiteVersionRepository(session).list_for_business(tenant.id, business.id)


# --- 2. Canonical hash ---------------------------------------------------------


def test_hash_is_independent_of_file_insertion_order():
    files = _site_artifact().files
    reordered = WebsiteArtifact(files=dict(reversed(list(files.items()))))
    assert artifact_sha256(reordered) == artifact_sha256(_site_artifact())


@pytest.mark.parametrize(
    ("path", "new_content"),
    [
        ("_headers", _HEADERS.replace(b"https://api.example.com", b"https://evil.example.com")),  # CSP
        ("_headers", _HEADERS + b"  X-Extra: 1\n"),
        ("_redirects", b"/old /elsewhere 301\n"),
        ("_astro/app.Ab12.js", b"window.gwaAnalytics={x:1};"),
        ("_astro/index.Cd34.css", b"body{color:red}"),
        ("index.html", b"<html>changed</html>"),
        ("privacy/index.html", b"<html>privacy v2</html>"),
        ("images/logo.png", bytes(range(255))),
    ],
    ids=["csp", "headers", "redirects", "js", "css", "html", "legal", "asset"],
)
def test_changing_any_single_file_changes_identity(path: str, new_content: bytes):
    original = _site_artifact()
    mutated = WebsiteArtifact(files={**original.files, path: new_content})
    assert artifact_sha256(mutated) != artifact_sha256(original)


def test_modifying_only_headers_changes_the_hash():
    """The explicit A8 CSP-incident regression: index.html + _headers,
    only _headers changes -> identity changes."""
    before = WebsiteArtifact(files={"index.html": b"<html></html>", "_headers": b"/*\n  X-Frame-Options: DENY\n"})
    after = WebsiteArtifact(files={"index.html": b"<html></html>", "_headers": b"/*\n  X-Frame-Options: SAMEORIGIN\n"})
    assert artifact_sha256(before) != artifact_sha256(after)


def test_adding_removing_or_renaming_a_file_changes_identity():
    original = _site_artifact()
    base = artifact_sha256(original)
    without_redirects = {k: v for k, v in original.files.items() if k != "_redirects"}
    assert artifact_sha256(WebsiteArtifact(files=without_redirects)) != base
    assert artifact_sha256(WebsiteArtifact(files={**original.files, "robots.txt": b""})) != base
    renamed = {**without_redirects, "_redirects.bak": original.files["_redirects"]}
    assert artifact_sha256(WebsiteArtifact(files=renamed)) != base


def test_hash_is_unambiguous_across_path_content_boundaries():
    one = WebsiteArtifact(files={"index.html": b"", "ab": b"c"})
    two = WebsiteArtifact(files={"index.html": b"", "a": b"bc"})
    assert artifact_sha256(one) != artifact_sha256(two)


@pytest.mark.parametrize("bad", ["../etc/passwd", "/abs.html", "a/../b", "a//b", "./a", "a\\b", "C:/x", "a\x00b", ""])
def test_hash_rejects_non_canonical_paths(bad: str):
    with pytest.raises(ArtifactPathError):
        artifact_sha256(WebsiteArtifact(files={"index.html": b"", bad: b"x"}))


# --- 3/4. Archive round trip + safety -----------------------------------------


def test_archive_round_trip_preserves_every_path_and_byte():
    original = _site_artifact()
    restored = unpack_artifact(pack_artifact(original))
    assert restored.files == original.files
    assert artifact_sha256(restored) == artifact_sha256(original)


def test_archive_bytes_are_deterministic():
    assert pack_artifact(_site_artifact()) == pack_artifact(WebsiteArtifact(files=dict(_site_artifact().files)))


def _tar_gz(*members: tuple[tarfile.TarInfo, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, content in members:
            tar.addfile(info, io.BytesIO(content) if content is not None else None)
    return buffer.getvalue()


def _file(name: str, content: bytes = b"x") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    return info, content


def _special(name: str, kind: bytes, linkname: str = "") -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info, None


@pytest.mark.parametrize(
    "members",
    [
        [_file("index.html"), _file("../escape.html")],
        [_file("index.html"), _file("/etc/cron.d/x")],
        [_file("index.html"), _file("a/../../b")],
        [_file("index.html"), _special("link", tarfile.SYMTYPE, "/etc/passwd")],
        [_file("index.html"), _special("hard", tarfile.LNKTYPE, "index.html")],
        [_file("index.html"), _special("dir", tarfile.DIRTYPE)],
        [_file("index.html"), _special("fifo", tarfile.FIFOTYPE)],
        [_file("index.html"), _file("index.html", b"second")],
        [_file("about.html")],
    ],
    ids=["traversal", "absolute", "nested-traversal", "symlink", "hardlink", "dir", "fifo", "duplicate", "no-index"],
)
def test_unpack_rejects_unsafe_archives(members):
    with pytest.raises(ArtifactArchiveCorruptError):
        unpack_artifact(_tar_gz(*members))


@pytest.mark.parametrize("garbage", [b"", b"not a gzip", b"\x1f\x8b\x08\x00garbage"])
def test_unpack_rejects_garbage(garbage: bytes):
    with pytest.raises(ArtifactArchiveCorruptError):
        unpack_artifact(garbage)


def test_unpack_rejects_a_truncated_archive():
    archive = pack_artifact(_site_artifact())
    with pytest.raises(ArtifactArchiveCorruptError):
        unpack_artifact(archive[: len(archive) // 2])


# --- 3. Storage key + write-once ----------------------------------------------


def test_storage_key_is_tenant_business_and_draft_scoped(tenant: Tenant, business: Business):
    draft_id = uuid.uuid4()
    key = draft_artifact_storage_key(tenant_id=tenant.id, business_id=business.id, draft_id=draft_id)
    assert key == f"website-drafts/{tenant.id.hex}/{business.id.hex}/{draft_id.hex}/artifact.tar.gz"


def test_stored_artifact_is_write_once(storage: LocalStorageProvider, tenant: Tenant, business: Business):
    kwargs = {"tenant_id": tenant.id, "business_id": business.id, "draft_id": uuid.uuid4()}
    stored = store_draft_artifact(storage, artifact=_site_artifact(), **kwargs)
    first_bytes = storage.load(stored.storage_key)

    with pytest.raises(ArtifactAlreadyExistsError):
        store_draft_artifact(storage, artifact=WebsiteArtifact(files={"index.html": b"other"}), **kwargs)
    assert storage.load(stored.storage_key) == first_bytes


# --- 15/16. Build once + byte equality (the hard acceptance criteria) ----------


def test_draft_is_built_exactly_once_and_publish_deploys_the_identical_bytes(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    assert builds.calls == 1
    [validated] = builds.produced
    original_hash = artifact_sha256(validated)
    assert draft.artifact_sha256 == original_hash

    publisher = RecordingPublisher()
    result = _publish(session, tenant, business, draft, publisher, storage)

    assert builds.calls == 1  # ZERO additional builds during publish
    [deployed] = publisher.artifacts
    assert deployed is not validated  # really reloaded from storage, not passed through in memory
    assert set(deployed.files) == set(validated.files)  # identical file set
    assert all(deployed.files[path] == validated.files[path] for path in validated.files)  # identical bytes
    assert deployed.files["_headers"] == _HEADERS
    assert artifact_sha256(deployed) == original_hash
    assert result.status is WebsiteStatus.LIVE
    assert draft.status is WebsiteDraftStatus.PUBLISHED


def test_a_published_version_is_traceable_to_its_draft_and_artifact(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    _publish(session, tenant, business, draft, RecordingPublisher(), storage)

    [version] = _versions(session, tenant, business)
    assert version.source_website_draft_id == draft.id
    assert version.artifact_sha256 == draft.artifact_sha256
    assert version.site_config == draft.site_config
    # "What exact artifact produced this version?" — answerable from the
    # version row alone, and it re-verifies against storage.
    source = session.get(WebsiteDraft, version.source_website_draft_id)
    reloaded = load_draft_artifact(
        storage, storage_key=source.artifact_key, expected_sha256=version.artifact_sha256, draft_id=source.id
    )
    assert artifact_sha256(reloaded) == version.artifact_sha256


def test_retrying_a_failed_publish_still_never_rebuilds(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    with pytest.raises(WebsitePublishError):
        _publish(session, tenant, business, draft, RecordingPublisher(fail=True), storage)
    publisher = RecordingPublisher()
    _publish(session, tenant, business, draft, publisher, storage)
    assert builds.calls == 1
    assert publisher.artifacts[0].files == builds.produced[0].files


# --- 14. Failure matrix -------------------------------------------------------


def test_A_success_produces_a_ready_artifact_backed_draft(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create(session, tenant, business, storage)
    assert draft.status is WebsiteDraftStatus.READY
    assert draft.artifact_key == draft_artifact_storage_key(
        tenant_id=tenant.id, business_id=business.id, draft_id=draft.id
    )
    assert len(draft.artifact_sha256) == 64
    assert storage.exists(draft.artifact_key)


def test_B_build_failure_stores_nothing_and_is_not_publishable(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, monkeypatch
):
    def _fail(site_config):
        raise WebsitePublisherError("astro build failed")

    monkeypatch.setattr("app.publishing.drafts.build_site", _fail)
    draft = _create(session, tenant, business, storage)
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.artifact_key is None and draft.artifact_sha256 is None
    assert _stored_archives(storage) == []
    with pytest.raises(WebsiteDraftError):
        approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)


def test_C_platform_contract_block_stores_nothing(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds, monkeypatch
):
    blocked = SimpleNamespace(passed=False, findings=[], blocking_violations=[SimpleNamespace(message="dead CTA")])
    monkeypatch.setattr("app.publishing.drafts.validate_platform_contract", lambda files, business_config: blocked)
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        storage=storage,
        business_config=SimpleNamespace(),
    )
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert "dead CTA" in draft.build_error
    assert draft.artifact_key is None and draft.artifact_sha256 is None
    assert _stored_archives(storage) == []


def test_D_storage_failure_never_produces_a_ready_draft(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds, monkeypatch
):
    def _broken_save(**kwargs):
        raise StorageProviderError("R2 upload failed")

    monkeypatch.setattr(storage, "save", _broken_save)
    live = _live_website(session, tenant, business)
    draft = _create(session, tenant, business, storage)

    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.artifact_key is None and draft.artifact_sha256 is None
    assert "could not be saved" in draft.build_error
    assert "R2" not in draft.build_error  # owner-facing, no internal detail
    with pytest.raises(WebsiteDraftError) as exc:
        approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    assert exc.value.code == "website_draft_not_ready"
    assert live.deploy_url == "https://live-before.pages.dev"


def _assert_refused_and_untouched(session, tenant, business, draft, storage, *, code: str, builds: BuildCounter):
    live = _live_website(session, tenant, business)
    builds_before = builds.calls
    publisher = RecordingPublisher()
    with pytest.raises(WebsiteDraftError) as exc:
        _publish(session, tenant, business, draft, publisher, storage)
    assert exc.value.code == code
    assert "unchanged" in str(exc.value)  # owner-facing reassurance
    assert publisher.artifacts == []  # no hosting-provider deployment at all
    assert _versions(session, tenant, business) == []  # no new current version
    assert live.status is WebsiteStatus.LIVE and live.deploy_url == "https://live-before.pages.dev"
    assert live.provider_deployment_id == "dep-live-before"
    assert draft.status is WebsiteDraftStatus.APPROVED
    assert builds.calls == builds_before  # never silently rebuilt


def test_E_missing_archive_refuses_safely(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    storage.delete(draft.artifact_key)
    _assert_refused_and_untouched(
        session, tenant, business, draft, storage, code="website_draft_artifact_unavailable", builds=builds
    )


def test_E_storage_outage_on_load_refuses_safely(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds, monkeypatch
):
    draft = _create_and_approve(session, tenant, business, storage)

    def _outage(key):
        raise StorageProviderError("R2 download failed")

    monkeypatch.setattr(storage, "load", _outage)
    _assert_refused_and_untouched(
        session, tenant, business, draft, storage, code="website_draft_artifact_unavailable", builds=builds
    )


def test_F_corrupted_archive_refuses_safely(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    path = storage._resolve(draft.artifact_key)
    path.write_bytes(path.read_bytes()[:40] + b"\x00corrupt\x00")
    _assert_refused_and_untouched(
        session, tenant, business, draft, storage, code="website_draft_artifact_integrity_failed", builds=builds
    )


def test_G_hash_mismatch_refuses_safely(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create_and_approve(session, tenant, business, storage)
    tampered = _site_artifact()
    tampered.files["_headers"] = b"/*\n  Content-Security-Policy: default-src *\n"  # a *valid* archive, wrong bytes
    storage._resolve(draft.artifact_key).write_bytes(pack_artifact(tampered))
    _assert_refused_and_untouched(
        session, tenant, business, draft, storage, code="website_draft_artifact_integrity_failed", builds=builds
    )


def test_G_load_draft_artifact_distinguishes_its_failure_modes(storage: LocalStorageProvider):
    key = "website-drafts/a/b/c/artifact.tar.gz"
    draft_id = uuid.uuid4()
    with pytest.raises(ArtifactUnavailableError):
        load_draft_artifact(storage, storage_key=key, expected_sha256="0" * 64, draft_id=draft_id)
    storage.save(storage_key=key, content=pack_artifact(_site_artifact()))
    with pytest.raises(ArtifactIntegrityError):
        load_draft_artifact(storage, storage_key=key, expected_sha256="0" * 64, draft_id=draft_id)
    storage.save(storage_key=key, content=b"garbage")
    with pytest.raises(ArtifactArchiveCorruptError):
        load_draft_artifact(storage, storage_key=key, expected_sha256="0" * 64, draft_id=draft_id)


def test_H_publisher_failure_leaves_existing_production_unchanged(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    live = _live_website(session, tenant, business)
    draft = _create_and_approve(session, tenant, business, storage)
    publisher = RecordingPublisher(fail=True)

    with pytest.raises(WebsitePublishError):
        _publish(session, tenant, business, draft, publisher, storage)

    assert len(publisher.artifacts) == 1  # the verified artifact was offered; the provider failed
    assert live.deploy_url == "https://live-before.pages.dev"
    assert live.provider_deployment_id == "dep-live-before"
    assert _versions(session, tenant, business) == []
    assert draft.status is WebsiteDraftStatus.APPROVED
    assert builds.calls == 1


# --- 10. Legacy drafts --------------------------------------------------------


def test_legacy_draft_without_artifact_is_refused_never_rebuilt(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    legacy = WebsiteDraft(
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config().model_dump(mode="json"),
        status=WebsiteDraftStatus.APPROVED,
    )
    session.add(legacy)
    session.flush()

    _assert_refused_and_untouched(
        session, tenant, business, legacy, storage, code="website_draft_artifact_missing", builds=builds
    )
    assert builds.calls == 0


# --- 7. Immutability ----------------------------------------------------------


def test_site_config_and_artifact_identity_are_write_once(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    draft = _create(session, tenant, business, storage)
    original_config = dict(draft.site_config)

    changed = _site_config().model_dump(mode="json")
    changed["brand"]["name"] = "Something else"
    with pytest.raises(ValueError):
        draft.site_config = changed
    with pytest.raises(ValueError):
        draft.artifact_sha256 = "f" * 64
    with pytest.raises(ValueError):
        draft.artifact_key = "website-drafts/x/y/z/artifact.tar.gz"
    with pytest.raises(ValueError):
        draft.artifact_sha256 = None

    draft.site_config = dict(original_config)  # re-assigning the identical value is harmless
    session.flush()
    session.expire_all()
    reloaded = session.get(WebsiteDraft, draft.id)
    assert reloaded.site_config == original_config


@pytest.fixture()
def client(session, storage: LocalStorageProvider, builds: BuildCounter):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_website_publisher] = lambda: RecordingPublisher()
    app.dependency_overrides[get_storage_provider] = lambda: storage
    try:
        yield TestClient(app)
    finally:
        for dep in (get_session, get_website_publisher, get_storage_provider):
            app.dependency_overrides.pop(dep, None)


def _api_create(client: TestClient, tenant: Tenant, business: Business) -> dict:
    created = client.post(
        f"/businesses/{business.id}/website-drafts",
        json={"site_config": _SITE_CONFIG},
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_no_api_flow_can_mutate_a_drafts_site_config(client: TestClient, tenant: Tenant, business: Business):
    headers = {"X-Tenant-Id": str(tenant.id)}
    draft = _api_create(client, tenant, business)
    assert draft["status"] == "ready"
    assert "artifact_key" not in draft  # the internal storage key is never exposed

    changed = {**_SITE_CONFIG, "brand": {"name": "Changed"}}
    url = f"/businesses/{business.id}/website-drafts/{draft['id']}"
    for method in ("put", "patch"):
        response = getattr(client, method)(url, json={"site_config": changed}, headers=headers)
        assert response.status_code == 405

    after = client.get(url, headers=headers).json()
    assert after["site_config"] == draft["site_config"]


def test_api_publish_of_an_artifact_backed_draft_never_rebuilds(
    client: TestClient, tenant: Tenant, business: Business, builds: BuildCounter
):
    headers = {"X-Tenant-Id": str(tenant.id)}
    draft = _api_create(client, tenant, business)
    base = f"/businesses/{business.id}/website-drafts/{draft['id']}"
    assert client.post(f"{base}/approve", headers=headers).status_code == 200
    published = client.post(f"{base}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "live"
    assert builds.calls == 1


def test_api_hash_mismatch_returns_a_safe_owner_facing_error(
    client: TestClient, session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider
):
    headers = {"X-Tenant-Id": str(tenant.id)}
    draft = _api_create(client, tenant, business)
    base = f"/businesses/{business.id}/website-drafts/{draft['id']}"
    client.post(f"{base}/approve", headers=headers)
    row = session.get(WebsiteDraft, uuid.UUID(draft["id"]))
    storage._resolve(row.artifact_key).write_bytes(pack_artifact(WebsiteArtifact(files={"index.html": b"x"})))

    response = client.post(f"{base}/publish", headers=headers)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "website_draft_artifact_integrity_failed"
    assert row.artifact_sha256[:12] not in error["message"]  # diagnostics stay internal
    assert "website-drafts/" not in error["message"]


# --- 10. Rollback / version republish (explicitly unchanged) ------------------


def test_rollback_still_republishes_from_site_config(
    session: Session, tenant: Tenant, business: Business, storage: LocalStorageProvider, builds: BuildCounter
):
    """Documented debt: rollback is operational recovery and still
    rebuilds from WebsiteVersion.site_config via publish_website — it is
    unaffected by this slice, and its versions carry no draft/hash."""
    draft = _create_and_approve(session, tenant, business, storage)
    _publish(session, tenant, business, draft, RecordingPublisher(), storage)
    [promoted] = _versions(session, tenant, business)

    result = rollback_to_version(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        version_id=promoted.id,
        publisher=RecordingPublisher(),
    )
    assert result.status is WebsiteStatus.LIVE
    assert builds.calls == 2  # the rollback's rebuild — never the draft publish
    versions = _versions(session, tenant, business)
    assert len(versions) == 2
    rollback_version = next(v for v in versions if v.id != promoted.id)
    assert rollback_version.source_website_draft_id is None
    assert rollback_version.artifact_sha256 is None


# --- 18. Migration ------------------------------------------------------------


def _alembic(db_url: str, *args: str) -> None:
    # A subprocess: migrations/env.py calls logging.config.fileConfig, which
    # would otherwise disable this test process's own loggers.
    env = {**os.environ, "DATABASE_URL": db_url}
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr


def _columns(db_url: str, table: str) -> dict:
    engine = sa.create_engine(db_url)
    try:
        return {column["name"]: column for column in sa.inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_migration_is_additive_nullable_and_reversible(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'migration.db'}"
    _alembic(db_url, "upgrade", PREVIOUS_REVISION)
    assert "artifact_sha256" not in _columns(db_url, "website_drafts")

    _alembic(db_url, "upgrade", NEW_REVISION)
    drafts = _columns(db_url, "website_drafts")
    versions = _columns(db_url, "website_versions")
    for column in (drafts["artifact_key"], drafts["artifact_sha256"], versions["artifact_sha256"]):
        assert column["nullable"] is True
    assert versions["source_website_draft_id"]["nullable"] is True

    _alembic(db_url, "downgrade", PREVIOUS_REVISION)
    assert "artifact_key" not in _columns(db_url, "website_drafts")
    assert "source_website_draft_id" not in _columns(db_url, "website_versions")

    _alembic(db_url, "upgrade", NEW_REVISION)
    assert "artifact_sha256" in _columns(db_url, "website_drafts")


def test_new_migration_is_the_single_head():
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=API_ROOT, capture_output=True, text=True, timeout=60
    )
    assert completed.stdout.split() == [NEW_REVISION, "(head)"]
