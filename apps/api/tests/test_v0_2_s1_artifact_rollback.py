"""v0.2 S1 — ARTIFACT-BACKED EXACT ROLLBACK.

Invariant: publishing and rollback operate on immutable WebsiteArtifacts,
not on reconstructed website configuration. An artifact-backed
WebsiteVersion is restored by redeploying its exact stored, SHA-verified
bytes — zero builds, zero generators, zero paid providers — and recorded as
a NEW version; every failure fails closed and never falls back to a
SiteConfig rebuild. Only historical rows without an artifact use the
isolated, non-exact legacy rebuild.

Deterministic fixtures only: fake artifacts, recording publishers, local
private storage. No network, no Anthropic, no Higgsfield.
"""

import io
import socket
import tarfile
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.website_draft import WebsiteDraft
from app.db.models.website_version import WebsiteVersion
from app.domain.enums import GenerationEngine, WebsiteDraftStatus
from app.publishing.artifact_store import artifact_sha256, pack_artifact, store_draft_artifact
from app.publishing.drafts import approve_website_draft, create_website_draft, publish_website_draft
from app.publishing.publisher import WebsiteArtifact
from app.publishing.service import WebsitePublishError, get_website_state, publish_prebuilt_artifact, publish_website
from app.publishing.versions import rollback_to_version
from app.repositories.website_version import WebsiteVersionRepository
from app.storage.errors import StorageProviderError
from app.storage.private import PrivateArtifactStorage
from tests import test_a8_real_draft_preview as _shared
from tests.test_a8_real_draft_preview import RecordingPublisher, _site_config
from tests.test_website_publish_service import FakePublisher

storage = _shared.storage  # private LocalStorageProvider-backed storage fixture


def _artifact(label: str) -> WebsiteArtifact:
    return WebsiteArtifact(
        files={
            "index.html": f"<html><body><form data-gwa-lead-form></form>{label}</body></html>".encode(),
            "_astro/app.js": f"window.v='{label}';".encode(),
            "privacy/index.html": b"<html>privacy</html>",
            "images/logo.png": bytes(range(256)),
            "_headers": b"/*\n  Content-Security-Policy: default-src 'self'\n",
            "_redirects": b"/old /new 301\n",
        }
    )


class _Tripwire:
    """Counts every way a website could be (re)generated or a paid provider
    reached. Artifact-backed rollback must leave all counters at zero."""

    def __init__(self) -> None:
        self.builds = 0
        self.generative_builds = 0
        self.frontend_generations = 0
        self.director_calls = 0
        self.next_label = "A"

    def build_site(self, site_config):
        self.builds += 1
        return _artifact(self.next_label)


@pytest.fixture()
def tripwire(monkeypatch: pytest.MonkeyPatch) -> _Tripwire:
    wire = _Tripwire()
    monkeypatch.setattr("app.publishing.drafts.build_site", wire.build_site)
    monkeypatch.setattr("app.publishing.service.build_site", wire.build_site)

    def _generative_build(*args, **kwargs):
        wire.generative_builds += 1
        raise AssertionError("generative build must never run during rollback")

    def _frontend_generate(self, **kwargs):
        wire.frontend_generations += 1
        raise AssertionError("the AI Frontend Engineer must never run during rollback")

    def _director(self, *args, **kwargs):
        wire.director_calls += 1
        raise AssertionError("no paid creative provider may run during rollback")

    monkeypatch.setattr("app.creative.frontend_engine.build.build_generative_workspace", _generative_build)
    monkeypatch.setattr("app.creative.frontend_engine.build.rebuild_from_archive", _generative_build)
    monkeypatch.setattr(
        "app.creative.frontend_engine.anthropic_engine.AnthropicFrontendEngine.generate", _frontend_generate
    )
    monkeypatch.setattr("app.creative.higgsfield.director._HiggsfieldDirectorBase.create_directions", _director)
    return wire


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("tests must never open a network connection")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket.socket, "connect", _refuse)


def _versions(session: Session, tenant: Tenant, business: Business) -> list[WebsiteVersion]:
    return WebsiteVersionRepository(session).list_for_business(tenant.id, business.id)


def _publish_basic(session, tenant, business, storage, tripwire, label: str) -> WebsiteVersion:
    """BASIC/legacy block path: draft (one build) -> approve -> publish."""
    tripwire.next_label = label
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        artifact_storage=storage,
    )
    session.flush()
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    publish_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        draft_id=draft.id,
        publisher=RecordingPublisher(),
        artifact_storage=storage,
    )
    session.flush()
    return _versions(session, tenant, business)[0]


def _publish_generative(session, tenant, business, storage, label: str) -> WebsiteVersion:
    """A generative version exactly as publish_generative_website_draft
    records it: no SiteConfig (a generative marker), the stored artifact's
    key/hash, and the source draft."""
    draft = WebsiteDraft(
        tenant_id=tenant.id,
        business_id=business.id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.APPROVED,
    )
    session.add(draft)
    session.flush()
    stored = store_draft_artifact(
        storage, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id, artifact=_artifact(label)
    )
    draft.artifact_key, draft.artifact_sha256 = stored.storage_key, stored.sha256
    publish_prebuilt_artifact(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        artifact=_artifact(label),
        config={"engine": "generative", "generator_provider": "fake", "workspace_key": "k"},
        publisher=RecordingPublisher(),
        source_website_draft_id=draft.id,
        artifact_sha256=stored.sha256,
        artifact_key=stored.storage_key,
    )
    session.flush()
    return _versions(session, tenant, business)[0]


def _rollback(session, tenant, business, version, storage, publisher=None):
    return rollback_to_version(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        version_id=version.id,
        publisher=publisher or RecordingPublisher(),
        artifact_storage=storage,
    )


def _snapshot(version: WebsiteVersion) -> tuple:
    return (
        version.site_config,
        version.deploy_url,
        version.provider_deployment_id,
        version.published_at,
        version.source_website_draft_id,
        version.artifact_sha256,
        version.artifact_key,
        version.rolled_back_from_version_id,
    )


# --- 1-6, 14-17: exact restore, zero builds/generators/providers --------------


def test_basic_artifact_backed_rollback_restores_exact_bytes_with_zero_builds(
    session, tenant, business, storage, tripwire
):
    version_a = _publish_basic(session, tenant, business, storage, tripwire, "A")
    _publish_basic(session, tenant, business, storage, tripwire, "B")
    builds_before = tripwire.builds
    before = _snapshot(version_a)

    publisher = RecordingPublisher()
    result = _rollback(session, tenant, business, version_a, storage, publisher)
    session.flush()

    assert result.status.value == "live"
    assert tripwire.builds == builds_before  # 1. zero builds
    assert tripwire.generative_builds == tripwire.frontend_generations == 0  # 2. zero generators
    assert tripwire.director_calls == 0  # 3. zero paid providers
    [restored] = publisher.artifacts
    assert restored.files == _artifact("A").files  # 6. exact historical bytes
    assert artifact_sha256(restored) == version_a.artifact_sha256

    versions = _versions(session, tenant, business)
    assert len(versions) == 3  # 14. a NEW version (A, B, D)
    rollback_version = versions[0]
    assert _snapshot(version_a) == before  # 15. the historical version is untouched
    assert rollback_version.id != version_a.id
    assert rollback_version.rolled_back_from_version_id == version_a.id  # 16. provenance
    assert rollback_version.source_website_draft_id == version_a.source_website_draft_id
    assert rollback_version.artifact_sha256 == version_a.artifact_sha256  # 17. correct hash
    assert rollback_version.artifact_key == version_a.artifact_key


def test_generative_version_without_site_config_rolls_back_exactly(session, tenant, business, storage, tripwire):
    version_a = _publish_generative(session, tenant, business, storage, "GEN-A")
    _publish_generative(session, tenant, business, storage, "GEN-B")
    assert version_a.site_config.get("engine") == "generative"  # no SiteConfig to rebuild

    publisher = RecordingPublisher()
    _rollback(session, tenant, business, version_a, storage, publisher)

    [restored] = publisher.artifacts
    assert restored.files == _artifact("GEN-A").files  # 4. exact bytes, no SiteConfig needed
    assert tripwire.builds == tripwire.generative_builds == tripwire.frontend_generations == 0
    assert tripwire.director_calls == 0
    assert _versions(session, tenant, business)[0].rolled_back_from_version_id == version_a.id


def test_rolling_back_to_a_rollback_version_still_restores_the_same_artifact(
    session, tenant, business, storage, tripwire
):
    version_a = _publish_basic(session, tenant, business, storage, tripwire, "A")
    _publish_basic(session, tenant, business, storage, tripwire, "B")
    _rollback(session, tenant, business, version_a, storage)
    session.flush()
    version_d = _versions(session, tenant, business)[0]
    _publish_basic(session, tenant, business, storage, tripwire, "C")

    publisher = RecordingPublisher()
    _rollback(session, tenant, business, version_d, storage, publisher)
    assert publisher.artifacts[0].files == _artifact("A").files


# --- 7-13, 19: fail closed, never a rebuild ------------------------------------


def _assert_failed_closed(session, tenant, business, exc_info, *, code, versions_before, tripwire, builds):
    assert exc_info.value.code == code
    assert len(_versions(session, tenant, business)) == versions_before  # no rollback version recorded
    assert tripwire.builds == builds  # 19. never a SiteConfig rebuild
    message = str(exc_info.value).lower()
    for leak in ("website-drafts/", "website-versions/", "r2", "presigned", "artifact.tar.gz"):
        assert leak not in message


def _prepare(session, tenant, business, storage, tripwire):
    version_a = _publish_basic(session, tenant, business, storage, tripwire, "A")
    _publish_basic(session, tenant, business, storage, tripwire, "B")
    return version_a, len(_versions(session, tenant, business)), tripwire.builds


def _replace_stored(storage: PrivateArtifactStorage, key: str, content: bytes) -> None:
    storage.delete(key)
    storage.save(storage_key=key, content=content)


def test_sha_is_verified_before_deployment_and_a_swapped_artifact_is_refused(
    session, tenant, business, storage, tripwire
):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    _replace_stored(storage, version_a.artifact_key, pack_artifact(_artifact("EVIL")))  # valid, but different bytes
    publisher = RecordingPublisher()

    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage, publisher)

    assert publisher.artifacts == []  # 7. verified BEFORE any deploy
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_integrity_failed", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_wrong_expected_sha_fails_closed(session, tenant, business, storage, tripwire):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    version_a.artifact_sha256 = "0" * 64  # 8. the recorded hash no longer matches the stored bytes
    publisher = RecordingPublisher()
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage, publisher)
    assert publisher.artifacts == []
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_integrity_failed", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_missing_artifact_fails_closed_without_rebuilding(session, tenant, business, storage, tripwire):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    storage.delete(version_a.artifact_key)  # 9. gone — and A still has a valid SiteConfig to tempt a rebuild
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage)
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_unavailable", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_corrupt_artifact_fails_closed(session, tenant, business, storage, tripwire):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    _replace_stored(storage, version_a.artifact_key, b"\x1f\x8b not really gzip")  # 10.
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage)
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_integrity_failed", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_invalid_archive_fails_closed(session, tenant, business, storage, tripwire):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:  # 11. well-formed tar.gz, but no index.html
        data = b"hello"
        info = tarfile.TarInfo("notes.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    _replace_stored(storage, version_a.artifact_key, buffer.getvalue())
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage)
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_integrity_failed", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_storage_failure_fails_closed(session, tenant, business, storage, tripwire, monkeypatch):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)

    def _down(storage_key):
        raise StorageProviderError("private bucket unavailable")

    monkeypatch.setattr(storage, "load", _down)  # 12.
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage)
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_artifact_unavailable", versions_before=count, tripwire=tripwire, builds=builds,
    )


def test_deployment_failure_records_no_rollback_and_keeps_the_live_url(session, tenant, business, storage, tripwire):
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    live_before = get_website_state(session=session, tenant_id=tenant.id, business_id=business.id)

    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage, FakePublisher(fail=True))  # 13.

    assert exc.value.code == "website_publish_failed"
    assert len(_versions(session, tenant, business)) == count
    assert tripwire.builds == builds
    live_after = get_website_state(session=session, tenant_id=tenant.id, business_id=business.id)
    assert live_after.live_url == live_before.live_url  # the previous deploy URL is untouched


def test_inconsistent_pre_s1_provenance_is_refused(session, tenant, business, storage, tripwire):
    """A pre-S1 row (no artifact_key) resolves through its source draft
    ONLY when the draft recorded the same hash."""
    version_a, count, builds = _prepare(session, tenant, business, storage, tripwire)
    version_a.artifact_key = None  # as recorded before S1
    publisher = RecordingPublisher()
    _rollback(session, tenant, business, version_a, storage, publisher)  # consistent: resolves via the draft
    assert publisher.artifacts[0].files == _artifact("A").files

    count = len(_versions(session, tenant, business))
    version_a.artifact_sha256 = "f" * 64  # the draft's hash no longer matches the version's
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version_a, storage)
    _assert_failed_closed(
        session, tenant, business, exc,
        code="website_version_not_restorable", versions_before=count, tripwire=tripwire, builds=builds,
    )


# --- 18: tenant isolation ------------------------------------------------------


def test_cross_tenant_rollback_is_forbidden(session, tenant, other_tenant, business, storage, tripwire):
    version_a = _publish_basic(session, tenant, business, storage, tripwire, "A")
    publisher = RecordingPublisher()
    with pytest.raises(WebsitePublishError) as exc:
        rollback_to_version(
            session=session,
            tenant_id=other_tenant.id,
            business_id=business.id,
            version_id=version_a.id,
            publisher=publisher,
            artifact_storage=storage,
        )
    assert exc.value.code == "website_version_not_found"
    assert publisher.artifacts == []


@pytest.fixture()
def api(session, storage, tripwire):
    from app.dependencies import get_private_artifact_storage, get_session, get_website_publisher
    from app.main import app

    publisher = RecordingPublisher()

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_private_artifact_storage] = lambda: storage
    app.dependency_overrides[get_website_publisher] = lambda: publisher
    client = TestClient(app)
    client.publisher = publisher  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        for dep in (get_session, get_private_artifact_storage, get_website_publisher):
            app.dependency_overrides.pop(dep, None)


def test_rollback_route_restores_exact_bytes_and_denies_other_tenants(
    api, session, tenant, other_tenant, business, storage, tripwire
):
    version_a = _publish_basic(session, tenant, business, storage, tripwire, "A")
    _publish_basic(session, tenant, business, storage, tripwire, "B")
    url = f"/businesses/{business.id}/website/versions/{version_a.id}/rollback"

    denied = api.post(url, headers={"X-Tenant-Id": str(other_tenant.id)})
    assert denied.status_code == 404  # 18. never another tenant's artifact
    assert api.publisher.artifacts == []

    response = api.post(url, headers={"X-Tenant-Id": str(tenant.id)})
    assert response.status_code == 200, response.text
    assert api.publisher.artifacts[0].files == _artifact("A").files
    for private in ("website-drafts/", "artifact_key", "sha256", "r2"):
        assert private not in response.text


# --- 20: every new modern version is artifact-backed ----------------------------


def test_new_versions_retain_durable_artifact_provenance(api, session, tenant, business, storage, tripwire):
    promoted = _publish_basic(session, tenant, business, storage, tripwire, "A")
    assert promoted.artifact_key and promoted.artifact_sha256  # draft promotion

    tripwire.next_label = "DIRECT"
    response = api.post(
        f"/businesses/{business.id}/website/publish",
        json=_shared._SITE_CONFIG,
        headers={"X-Tenant-Id": str(tenant.id)},
    )
    assert response.status_code == 200, response.text
    direct = _versions(session, tenant, business)[0]
    assert direct.artifact_key and direct.artifact_key.startswith("website-versions/")  # the legacy route too
    assert direct.artifact_sha256 == artifact_sha256(_artifact("DIRECT"))


# --- Legacy compatibility (isolated) -------------------------------------------


def test_legacy_version_without_artifact_uses_the_isolated_rebuild_and_becomes_artifact_backed(
    session, tenant, business, storage, tripwire
):
    """A historical row with no artifact (published before S1 without
    storage) is rebuilt from its SiteConfig — NOT exact-byte — and the
    resulting rollback version stores what it built."""
    tripwire.next_label = "OLD"
    publish_website(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        publisher=RecordingPublisher(),
    )
    session.flush()
    [legacy] = _versions(session, tenant, business)
    assert legacy.artifact_sha256 is None and legacy.artifact_key is None

    tripwire.next_label = "REBUILT"
    _rollback(session, tenant, business, legacy, storage)
    session.flush()
    rebuilt = _versions(session, tenant, business)[0]
    assert tripwire.builds == 2  # the legacy rebuild — explicitly not exact-byte
    assert rebuilt.rolled_back_from_version_id == legacy.id
    assert rebuilt.artifact_key and rebuilt.artifact_sha256 == artifact_sha256(_artifact("REBUILT"))


def test_generative_snapshot_without_an_artifact_is_refused_cleanly_never_rebuilt(
    session, tenant, business, storage, tripwire
):
    version = WebsiteVersion(
        tenant_id=tenant.id,
        business_id=business.id,
        site_config={"engine": "generative"},
        deploy_url="https://x.pages.dev",
        published_at=datetime.now(UTC),
    )
    session.add(version)
    session.flush()
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, version, storage)
    assert exc.value.code == "website_version_not_restorable"
    assert exc.value.status_code == 409  # previously an unhandled 500
    assert tripwire.builds == 0


def test_unknown_version_is_still_a_404(session, tenant, business, storage, tripwire):
    with pytest.raises(WebsitePublishError) as exc:
        _rollback(session, tenant, business, WebsiteVersion(id=uuid.uuid4()), storage)
    assert exc.value.code == "website_version_not_found"


# --- Migration -----------------------------------------------------------------


def test_s1_migration_is_additive_reversible_and_the_single_head(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import sqlalchemy as sa

    api_root = Path(__file__).resolve().parents[1]
    db_url = f"sqlite:///{tmp_path / 'm.db'}"

    def alembic(*args: str) -> str:
        env = {**os.environ, "DATABASE_URL": db_url}
        done = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=api_root, env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def columns() -> dict:
        engine = sa.create_engine(db_url)
        try:
            return {c["name"]: c for c in sa.inspect(engine).get_columns("website_versions")}
        finally:
            engine.dispose()

    alembic("upgrade", "e6f9a2b3c4d5")
    assert "artifact_key" not in columns()
    alembic("upgrade", "f1a7c3e9b2d4")
    cols = columns()
    for name in ("artifact_key", "rolled_back_from_version_id"):
        assert cols[name]["nullable"] is True  # no backfill; historical rows stay without provenance
    alembic("downgrade", "e6f9a2b3c4d5")
    assert "rolled_back_from_version_id" not in columns()
    alembic("upgrade", "head")
    assert len(alembic("heads").split("\n")[0].split()) == 2  # a single head (later revisions may follow)
