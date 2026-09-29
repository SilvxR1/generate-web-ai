"""A8.4 — FIRST WEBSITE ARTIFACT PROMOTION.

A business that has never had a website goes live through the SAME
WebsiteDraft lifecycle as a redesign — no second pipeline:

SiteConfig -> WebsiteDraft (ONE build, PlatformContract, private artifact)
-> READY -> real preview (zero builds) -> explicit approval -> publish
(zero builds) -> the business's FIRST Website + WebsiteVersion, traceable to
the draft and its artifact hash.

Every business here starts with NO Website row and NO WebsiteVersion; the
failure cases prove such a business still has no live website afterwards.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.enums import WebsiteDraftStatus
from app.publishing.artifact_store import artifact_sha256
from app.publishing.drafts import (
    WebsiteDraftError,
    approve_website_draft,
    create_website_draft,
    publish_website_draft,
)
from app.publishing.errors import WebsitePublisherError
from app.publishing.service import WebsitePublishError, get_website_state
from app.repositories.website_version import WebsiteVersionRepository
from app.storage.private import PrivateArtifactStorage
from tests import test_a8_real_draft_preview as _shared
from tests.test_a8_real_draft_preview import (
    _HEADERS,
    _SITE_CONFIG,
    BuildCounter,
    RecordingPreviewPublisher,
    RecordingPublisher,
    _preview,
    _site_config,
)

# Shared A8.3.4.2a fixtures: the build counter (patches build_site in both
# drafts and service), private storage and the API client wired to the
# recording publishers. Re-registered here, not duplicated.
builds = _shared.builds
storage = _shared.storage
client = _shared.client

_PASSED = SimpleNamespace(passed=True, findings=[], blocking_violations=[])


def _versions(session: Session, tenant: Tenant, business: Business):
    return WebsiteVersionRepository(session).list_for_business(tenant.id, business.id)


def _assert_no_website(session: Session, tenant: Tenant, business: Business) -> None:
    state = get_website_state(session=session, tenant_id=tenant.id, business_id=business.id)
    assert state is None or (state.status.value != "live" and state.live_url is None)
    assert _versions(session, tenant, business) == []


@pytest.fixture()
def contract_calls(monkeypatch: pytest.MonkeyPatch) -> list[set[str]]:
    """Records every PlatformContract scan (the files it saw) and passes."""
    calls: list[set[str]] = []

    def _validate(files, business_config):
        calls.append(set(files))
        return _PASSED

    monkeypatch.setattr("app.publishing.drafts.validate_platform_contract", _validate)
    return calls


def _first_site_draft(session, tenant, business, storage):
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=_site_config(),
        artifact_storage=storage,
        business_config=SimpleNamespace(),  # the real route always passes it
    )
    session.flush()
    return draft


def _approve(session, tenant, business, draft):
    return approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)


def _publish(session, tenant, business, draft, storage, publisher, preview_publisher=None):
    return publish_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        draft_id=draft.id,
        publisher=publisher,
        artifact_storage=storage,
        preview_publisher=preview_publisher,
    )


# --- The happy path: first website, one build, same bytes everywhere --------


def test_first_website_goes_live_through_the_draft_lifecycle_with_one_build_and_identical_bytes(
    session: Session,
    tenant: Tenant,
    business: Business,
    storage: PrivateArtifactStorage,
    builds: BuildCounter,
    contract_calls,
):
    _assert_no_website(session, tenant, business)  # truly a first website

    draft = _first_site_draft(session, tenant, business, storage)
    assert draft.status is WebsiteDraftStatus.READY
    assert builds.calls == 1
    assert len(contract_calls) == 1 and "_headers" in contract_calls[0]  # PlatformContract ran on the build
    assert draft.artifact_key is not None and draft.artifact_sha256 is not None
    _assert_no_website(session, tenant, business)  # drafting never publishes

    preview_publisher = RecordingPreviewPublisher()
    _preview(session, tenant, business, draft, storage, preview_publisher)
    assert builds.calls == 1  # preview: zero builds
    assert draft.status is WebsiteDraftStatus.READY  # preview never approves
    _assert_no_website(session, tenant, business)  # preview never publishes

    _approve(session, tenant, business, draft)
    assert draft.status is WebsiteDraftStatus.APPROVED
    _assert_no_website(session, tenant, business)  # approval never publishes

    production = RecordingPublisher()
    result = _publish(session, tenant, business, draft, storage, production, preview_publisher)
    assert builds.calls == 1  # publish: zero builds — ONE build in total

    assert result.status.value == "live"
    assert draft.status is WebsiteDraftStatus.PUBLISHED

    [built] = builds.produced
    [(_, previewed)] = preview_publisher.deployed
    [published] = production.artifacts
    assert set(built.files) == set(previewed.files) == set(published.files)
    for path in built.files:  # byte-for-byte, every file
        assert built.files[path] == previewed.files[path] == published.files[path], path
    for path in ("_headers", "_redirects", "index.html", "privacy/index.html", "images/logo.png"):
        assert path in published.files
    assert published.files["_headers"] == _HEADERS
    assert artifact_sha256(built) == artifact_sha256(previewed) == artifact_sha256(published) == draft.artifact_sha256

    [version] = _versions(session, tenant, business)  # the business's FIRST version
    assert version.source_website_draft_id == draft.id
    assert version.artifact_sha256 == draft.artifact_sha256
    assert draft.published_website_id == version.website_id


# --- Approval gates ----------------------------------------------------------


def test_a_ready_first_site_draft_cannot_be_published_without_approval(
    session, tenant, business, storage, builds, contract_calls
):
    draft = _first_site_draft(session, tenant, business, storage)
    production = RecordingPublisher()

    with pytest.raises(WebsiteDraftError) as exc:
        _publish(session, tenant, business, draft, storage, production)

    assert exc.value.code == "website_draft_not_approved"
    assert production.artifacts == []
    assert draft.status is WebsiteDraftStatus.READY
    _assert_no_website(session, tenant, business)


# --- Failure safety: a business without a website still has none -------------


def test_build_failure_leaves_the_business_without_a_website(session, tenant, business, storage, monkeypatch):
    def _fail(site_config):
        raise WebsitePublisherError("astro build failed")

    monkeypatch.setattr("app.publishing.drafts.build_site", _fail)
    draft = _first_site_draft(session, tenant, business, storage)

    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.artifact_key is None
    with pytest.raises(WebsiteDraftError):
        _approve(session, tenant, business, draft)
    with pytest.raises(WebsiteDraftError):
        _publish(session, tenant, business, draft, storage, RecordingPublisher())
    _assert_no_website(session, tenant, business)


def test_platform_contract_failure_leaves_the_business_without_a_website(
    session, tenant, business, storage, builds, monkeypatch
):
    blocked = SimpleNamespace(passed=False, findings=[], blocking_violations=[SimpleNamespace(message="dead CTA")])
    monkeypatch.setattr("app.publishing.drafts.validate_platform_contract", lambda files, business_config: blocked)
    draft = _first_site_draft(session, tenant, business, storage)

    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.artifact_key is None
    with pytest.raises(WebsiteDraftError):
        _approve(session, tenant, business, draft)
    _assert_no_website(session, tenant, business)


def test_preview_failure_leaves_the_business_without_a_website(
    session, tenant, business, storage, builds, contract_calls
):
    draft = _first_site_draft(session, tenant, business, storage)

    with pytest.raises(WebsiteDraftError) as exc:
        _preview(session, tenant, business, draft, storage, RecordingPreviewPublisher(fail=True))

    assert exc.value.code == "website_draft_preview_failed"
    assert draft.status is WebsiteDraftStatus.READY
    _assert_no_website(session, tenant, business)


def test_publish_failure_leaves_the_business_without_a_live_website_and_the_draft_approved(
    session, tenant, business, storage, builds, contract_calls
):
    class _FailingPublisher(RecordingPublisher):
        def publish(self, *, site_id, artifact):
            self.artifacts.append(artifact)
            raise WebsitePublisherError("wrangler deploy failed")

    draft = _first_site_draft(session, tenant, business, storage)
    _approve(session, tenant, business, draft)

    with pytest.raises(WebsitePublishError) as exc:
        _publish(session, tenant, business, draft, storage, _FailingPublisher())

    assert exc.value.code == "website_publish_failed"
    assert builds.calls == 1  # a failed publish never rebuilds either
    assert draft.status is WebsiteDraftStatus.APPROVED  # retryable without re-approving
    _assert_no_website(session, tenant, business)


# --- Through the real API routes Studio calls ---------------------------------


def test_first_site_api_flow_draft_preview_approve_publish(
    client: TestClient, session, tenant, business, builds: BuildCounter, contract_calls
):
    headers = {"X-Tenant-Id": str(tenant.id)}
    base = f"/businesses/{business.id}"
    assert client.get(f"{base}/website", headers=headers).json() is None

    created = client.post(
        f"{base}/website-drafts", json={"site_config": _SITE_CONFIG, "creative_generation_id": None}, headers=headers
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["status"] == "ready"
    assert "artifact" not in created.text  # never exposed to Studio

    early = client.post(f"{base}/website-drafts/{draft['id']}/publish", headers=headers)
    assert early.status_code == 409 and early.json()["error"]["code"] == "website_draft_not_approved"

    preview = client.post(f"{base}/website-drafts/{draft['id']}/preview", headers=headers)
    assert preview.status_code == 200, preview.text
    assert client.get(f"{base}/website-drafts/{draft['id']}", headers=headers).json()["status"] == "ready"

    approved = client.post(f"{base}/website-drafts/{draft['id']}/approve", headers=headers)
    assert approved.json()["status"] == "approved"
    assert client.get(f"{base}/website", headers=headers).json() is None  # still nothing live

    published = client.post(f"{base}/website-drafts/{draft['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "live"
    assert builds.calls == 1

    [version] = client.get(f"{base}/website/versions", headers=headers).json()
    [stored] = _versions(session, tenant, business)
    assert stored.source_website_draft_id is not None and str(stored.source_website_draft_id) == draft["id"]
    assert version["id"] == str(stored.id)
