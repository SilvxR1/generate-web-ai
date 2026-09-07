"""publish_website/unpublish_website/get_website_state
(app.publishing.service) against a fake WebsitePublisher and a real
(sqlite, in-memory) session: first publish persists, publish failure
leaves the previous live state unchanged (never marks anything
Published), unpublish takes a live site down for real and never just
flips a local flag, reload/get returns the persisted state, tenant
isolation, and that nothing about the fake provider's "credential" ever
appears in the result.

app.publishing.build.build_site is monkeypatched to a fake, instant
build here — these tests are about the persistence/orchestration
boundary, not build fidelity (see test_site_builder_integration.py for
the real, unmocked `astro build` proof) or Cloudflare's wire protocol
(see test_cloudflare_pages_publisher.py)."""

import json

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.enums import WebsiteStatus
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.publishing.service import (
    WebsitePublishError,
    get_website_state,
    publish_website,
    unpublish_website,
)
from app.schemas.site_config import SiteConfigPayload

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
    "pages": [
        {
            "path": "/",
            "blocks": [{"type": "hero", "content": {"heading": "Tu reforma, sin sorpresas"}}],
        }
    ],
}

SECRET = "fake-provider-secret-token"

_FAKE_ARTIFACT = WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: _FAKE_ARTIFACT)


class FakePublisher(WebsitePublisher):
    """A WebsitePublisher a test controls directly — no HTTP involved —
    for asserting behavior around the domain boundary itself, the same
    role a hand-rolled fake plays alongside the httpx-mocked
    CloudflarePagesPublisher tests (see test_cloudflare_pages_publisher.py)."""

    def __init__(self, *, fail: bool = False, fail_unpublish: bool = False) -> None:
        self.fail = fail
        self.fail_unpublish = fail_unpublish
        self.publish_calls: list[tuple[str, WebsiteArtifact]] = []
        self.unpublish_calls: list[str] = []
        # Stands in for a real publisher's held API credential — never
        # touched by publish()/get_status(), just present to prove
        # nothing about it can leak into a WebsiteStateResult.
        self._token = SECRET

    def publish(self, *, site_id: str, artifact: WebsiteArtifact) -> PublishedSite:
        self.publish_calls.append((site_id, artifact))
        if self.fail:
            raise WebsitePublisherError("provider rejected the deploy")
        return PublishedSite(deployment_id=site_id, url=f"https://{site_id}.example.pages.dev", live=True)

    def unpublish(self, deployment_id: str) -> None:
        self.unpublish_calls.append(deployment_id)
        if self.fail_unpublish:
            raise WebsitePublisherError("provider rejected the unpublish")

    def get_status(self, deployment_id: str) -> PublishedSite:
        return PublishedSite(deployment_id=deployment_id, url=f"https://{deployment_id}.example.pages.dev", live=True)


def _site_config(**overrides: object) -> SiteConfigPayload:
    return SiteConfigPayload.model_validate({**_SITE_CONFIG, **overrides})


def _publish(session: Session, business: Business, publisher: WebsitePublisher, **overrides: object):
    return publish_website(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        site_config=_site_config(**overrides),
        publisher=publisher,
    )


# --- first publish ------------------------------------------------------


def test_first_publish_persists_website_state(session: Session, business: Business):
    result = _publish(session, business, FakePublisher())

    assert result.status is WebsiteStatus.LIVE
    assert result.live_url == f"https://site-{business.id.hex}.example.pages.dev/"
    assert result.deployment_id == f"site-{business.id.hex}"
    assert result.deployed_at is not None

    reloaded = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert reloaded is not None
    assert reloaded.status is WebsiteStatus.LIVE
    assert reloaded.live_url == result.live_url


def test_publish_uses_a_real_build_artifact_not_a_bare_html_string(session: Session, business: Business):
    publisher = FakePublisher()
    _publish(session, business, publisher)

    assert len(publisher.publish_calls) == 1
    _, artifact = publisher.publish_calls[0]
    assert isinstance(artifact, WebsiteArtifact)
    assert "index.html" in artifact.files


def test_publish_never_leaks_the_provider_secret(session: Session, business: Business):
    result = _publish(session, business, FakePublisher())

    dumped = json.dumps(result.model_dump(mode="json"))
    assert SECRET not in dumped
    assert SECRET not in repr(result)


# --- republish updates the live site -------------------------------------


def test_republish_updates_the_persisted_state(session: Session, business: Business):
    first = _publish(session, business, FakePublisher())
    second = _publish(session, business, FakePublisher())

    assert second.status is WebsiteStatus.LIVE
    assert second.deployed_at is not None
    assert first.deployed_at is not None
    assert second.deployed_at >= first.deployed_at


# --- publish failure ------------------------------------------------------


def test_publish_failure_is_reported_and_never_marks_live(session: Session, business: Business):
    with pytest.raises(WebsitePublishError) as exc_info:
        _publish(session, business, FakePublisher(fail=True))

    assert exc_info.value.code == "website_publish_failed"
    assert SECRET not in str(exc_info.value)

    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.FAILED
    assert state.live_url is None


def test_publish_failure_after_a_successful_publish_keeps_the_previous_live_url(
    session: Session, business: Business
):
    live = _publish(session, business, FakePublisher())

    with pytest.raises(WebsitePublishError):
        _publish(session, business, FakePublisher(fail=True))

    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.FAILED
    # The site Cloudflare is still actually serving doesn't disappear
    # just because a later republish attempt failed.
    assert state.live_url == live.live_url
    assert state.deployed_at == live.deployed_at


def test_build_failure_is_reported_the_same_way_as_a_provider_failure(
    session: Session, business: Business, monkeypatch: pytest.MonkeyPatch
):
    from app.publishing.build import SiteBuildError

    def _failing_build(site_config: SiteConfigPayload) -> WebsiteArtifact:
        raise SiteBuildError("astro build failed")

    monkeypatch.setattr("app.publishing.service.build_site", _failing_build)

    def must_not_be_called(**kwargs: object) -> PublishedSite:
        raise AssertionError("must not call the publisher when the build itself failed")

    publisher = FakePublisher()
    publisher.publish = must_not_be_called  # type: ignore[method-assign]

    with pytest.raises(WebsitePublishError) as exc_info:
        _publish(session, business, publisher)

    assert exc_info.value.code == "website_publish_failed"
    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.FAILED


# --- reload / get ---------------------------------------------------------


def test_get_website_state_returns_none_before_any_publish(session: Session, business: Business):
    assert get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id) is None


# --- unpublish --------------------------------------------------------------


def test_unpublish_takes_a_live_site_down_and_clears_the_live_url(session: Session, business: Business):
    published = _publish(session, business, FakePublisher())
    publisher = FakePublisher()

    result = unpublish_website(
        session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=publisher
    )

    assert result.status is WebsiteStatus.INACTIVE
    assert result.live_url is None
    assert publisher.unpublish_calls == [f"site-{business.id.hex}"]

    reloaded = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert reloaded is not None
    assert reloaded.status is WebsiteStatus.INACTIVE
    assert reloaded.live_url is None
    assert published.live_url is not None  # sanity: it really was live before this


def test_unpublish_calls_the_real_provider_not_just_a_local_flag_flip(session: Session, business: Business):
    _publish(session, business, FakePublisher())
    publisher = FakePublisher()

    unpublish_website(session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=publisher)

    assert len(publisher.unpublish_calls) == 1


def test_unpublish_without_any_prior_publish_is_rejected(session: Session, business: Business):
    with pytest.raises(WebsitePublishError) as exc_info:
        unpublish_website(
            session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=FakePublisher()
        )

    assert exc_info.value.code == "website_not_published"


def test_unpublish_is_idempotent_when_already_inactive(session: Session, business: Business):
    publisher = FakePublisher()
    _publish(session, business, FakePublisher())
    unpublish_website(session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=publisher)
    publisher.unpublish_calls.clear()

    result = unpublish_website(
        session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=publisher
    )

    assert result.status is WebsiteStatus.INACTIVE
    # Already inactive — must not call the provider again.
    assert publisher.unpublish_calls == []


def test_unpublish_provider_failure_leaves_the_site_reported_live(session: Session, business: Business):
    live = _publish(session, business, FakePublisher())

    with pytest.raises(WebsitePublishError) as exc_info:
        unpublish_website(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            publisher=FakePublisher(fail_unpublish=True),
        )

    assert exc_info.value.code == "website_unpublish_failed"
    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.LIVE
    assert state.live_url == live.live_url


def test_unpublish_never_leaks_the_provider_secret(session: Session, business: Business):
    _publish(session, business, FakePublisher())

    result = unpublish_website(
        session=session, tenant_id=business.tenant_id, business_id=business.id, publisher=FakePublisher()
    )

    dumped = json.dumps(result.model_dump(mode="json"))
    assert SECRET not in dumped
    assert SECRET not in repr(result)


# --- tenant isolation -------------------------------------------------------


def test_tenant_isolation_website_not_visible_to_another_tenant(
    session: Session, business: Business, other_tenant: Tenant
):
    _publish(session, business, FakePublisher())

    state = get_website_state(session=session, tenant_id=other_tenant.id, business_id=business.id)

    assert state is None


def test_unpublish_never_leaks_across_tenants(session: Session, business: Business, other_tenant: Tenant):
    _publish(session, business, FakePublisher())

    with pytest.raises(WebsitePublishError) as exc_info:
        unpublish_website(
            session=session, tenant_id=other_tenant.id, business_id=business.id, publisher=FakePublisher()
        )

    assert exc_info.value.code == "website_not_published"
    still_live = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert still_live is not None
    assert still_live.status is WebsiteStatus.LIVE
