"""create_website_draft/approve_website_draft/publish_website_draft
(app.publishing.drafts): build/validate on create, explicit approval
required before publish, and that the currently published Website row is
untouched by anything short of a successful publish_website_draft call.

app.publishing.drafts.build_site is monkeypatched to a fake, instant build
here — mirrors test_website_publish_service.py's own convention (real,
unmocked `astro build` is proven separately by
test_site_builder_integration.py)."""

import json

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.enums import WebsiteDraftStatus
from app.publishing.drafts import (
    WebsiteDraftError,
    approve_website_draft,
    create_website_draft,
    publish_website_draft,
)
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.publishing.service import get_website_state
from app.repositories.website_draft import WebsiteDraftRepository
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

_FAKE_ARTIFACT = WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})


def _site_config() -> SiteConfigPayload:
    return SiteConfigPayload.model_validate(json.loads(json.dumps(_SITE_CONFIG)))


class FakePublisher(WebsitePublisher):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.publish_calls: list[str] = []

    def publish(self, *, site_id, artifact):
        self.publish_calls.append(site_id)
        if self.fail:
            raise WebsitePublisherError("simulated hosting provider failure")
        return PublishedSite(deployment_id="dep-1", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.publishing.drafts.build_site", lambda site_config: _FAKE_ARTIFACT)


def test_create_website_draft_builds_and_marks_ready(session: Session, tenant: Tenant, business: Business):
    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )

    assert draft.status is WebsiteDraftStatus.READY
    assert draft.build_error is None
    assert draft.site_config["brand"]["name"] == "Reforma Casa Valencia"


def test_create_website_draft_never_touches_production_when_build_fails(
    session: Session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "app.publishing.drafts.build_site",
        lambda site_config: (_ for _ in ()).throw(WebsitePublisherError("astro build failed")),
    )

    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )

    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.build_error == "astro build failed"
    assert get_website_state(session=session, tenant_id=tenant.id, business_id=business.id) is None


def test_website_draft_persists_validation_issues_without_blocking_ready_status(
    session: Session, tenant: Tenant, business: Business
):
    incomplete = _site_config()
    incomplete.seo.title = ""

    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=incomplete
    )

    # Validation issues are non-blocking (Phase 17: a human weighs them),
    # never SEO title emptiness alone forcing a real, publishable build
    # into a hard-failed state.
    assert draft.status is WebsiteDraftStatus.READY
    assert draft.validation_issues is not None
    assert any("SEO title" in issue for issue in draft.validation_issues)


def test_approve_requires_a_ready_draft(
    session: Session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "app.publishing.drafts.build_site",
        lambda site_config: (_ for _ in ()).throw(WebsitePublisherError("boom")),
    )
    failed_draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )
    session.flush()

    with pytest.raises(WebsiteDraftError) as exc_info:
        approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=failed_draft.id)
    assert exc_info.value.code == "website_draft_not_ready"
    assert exc_info.value.status_code == 409


def test_publish_requires_an_approved_draft(session: Session, tenant: Tenant, business: Business):
    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )
    session.flush()

    with pytest.raises(WebsiteDraftError) as exc_info:
        publish_website_draft(
            session=session,
            tenant_id=tenant.id,
            business_id=business.id,
            draft_id=draft.id,
            publisher=FakePublisher(),
        )
    assert exc_info.value.code == "website_draft_not_approved"
    assert exc_info.value.status_code == 409
    # Never published just because publish was attempted on a READY (not
    # yet APPROVED) draft.
    assert get_website_state(session=session, tenant_id=tenant.id, business_id=business.id) is None


def test_full_lifecycle_generate_build_approve_publish(session: Session, tenant: Tenant, business: Business):
    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )
    session.flush()
    assert draft.status is WebsiteDraftStatus.READY

    approved = approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    assert approved.status is WebsiteDraftStatus.APPROVED
    assert approved.approved_at is not None
    session.flush()

    publisher = FakePublisher()
    result = publish_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id, publisher=publisher
    )

    assert result.status.value == "live"
    assert publisher.publish_calls == [f"site-{business.id.hex}"]
    assert draft.status is WebsiteDraftStatus.PUBLISHED
    assert draft.published_at is not None
    assert draft.published_website_id is not None


def test_publish_failure_leaves_the_draft_approved_not_published(
    session: Session, tenant: Tenant, business: Business
):
    draft = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=draft.id)
    session.flush()

    from app.publishing.service import WebsitePublishError

    with pytest.raises(WebsitePublishError):
        publish_website_draft(
            session=session,
            tenant_id=tenant.id,
            business_id=business.id,
            draft_id=draft.id,
            publisher=FakePublisher(fail=True),
        )

    assert draft.status is WebsiteDraftStatus.APPROVED
    assert draft.published_at is None
    # publish_website's own established behavior (see
    # test_website_publish_service.py's
    # test_publish_failure_is_reported_and_never_marks_live): a first-ever
    # failed attempt still records a FAILED Website row rather than
    # nothing at all — what this test actually needs to prove is that
    # nothing was reported LIVE and the draft itself was never marked
    # PUBLISHED.
    from app.domain.enums import WebsiteStatus

    state = get_website_state(session=session, tenant_id=tenant.id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.FAILED
    assert state.live_url is None


def test_regeneration_creates_a_new_draft_without_touching_a_previous_one(
    session: Session, tenant: Tenant, business: Business
):
    first = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=_site_config()
    )
    session.flush()
    approve_website_draft(session=session, tenant_id=tenant.id, business_id=business.id, draft_id=first.id)
    session.flush()

    second_config = _site_config()
    second_config.brand.tagline = "Nueva direccion creativa"
    second = create_website_draft(
        session=session, tenant_id=tenant.id, business_id=business.id, site_config=second_config
    )

    assert second.id != first.id
    assert first.status is WebsiteDraftStatus.APPROVED  # untouched by the second generation
    all_drafts = WebsiteDraftRepository(session).list_for_business(tenant.id, business.id)
    assert {d.id for d in all_drafts} == {first.id, second.id}
