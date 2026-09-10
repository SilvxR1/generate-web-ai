"""list_website_versions/rollback_to_version (app.publishing.versions)
against a fake WebsitePublisher and a real (sqlite, in-memory) session:
every successful publish appends a version, rollback republishes an old
snapshot through the real publish_website path (never a second deploy
mechanism), a failed rollback leaves the currently-live site reported
live and never deletes any version, rolling back creates a new version
rather than rewriting history, and tenant isolation.

Reuses test_website_publish_service.py's FakePublisher/fake build — see
that module's own docstring for why."""

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.enums import WebsiteStatus
from app.publishing.service import WebsitePublishError, get_website_state, publish_website
from app.publishing.versions import list_website_versions, rollback_to_version
from tests.test_website_publish_service import _FAKE_ARTIFACT, FakePublisher, _site_config


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    # Same fake-build swap test_website_publish_service.py's own autouse
    # fixture does — it doesn't apply here just because this file
    # imports names from that module, and these tests are about version
    # bookkeeping/rollback, not build fidelity.
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: _FAKE_ARTIFACT)


def _publish(session: Session, business: Business, publisher=None, **overrides: object):
    return publish_website(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        site_config=_site_config(**overrides),
        publisher=publisher or FakePublisher(),
    )


# --- list_website_versions ---------------------------------------------------


def test_list_versions_is_empty_before_any_publish(session: Session, business: Business):
    assert list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id) == []


def test_first_publish_creates_exactly_one_version_flagged_current(session: Session, business: Business):
    _publish(session, business)

    versions = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert len(versions) == 1
    assert versions[0].is_current is True


def test_each_successful_publish_appends_a_new_version_most_recent_first(session: Session, business: Business):
    first = _publish(session, business)
    second = _publish(session, business)

    versions = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert len(versions) == 2
    assert versions[0].is_current is True
    assert versions[1].is_current is False
    assert versions[0].published_at >= versions[1].published_at
    assert first.deployed_at is not None
    assert second.deployed_at is not None


def test_a_failed_publish_does_not_append_a_version(session: Session, business: Business):
    _publish(session, business)

    with pytest.raises(WebsitePublishError):
        _publish(session, business, publisher=FakePublisher(fail=True))

    versions = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert len(versions) == 1


# --- rollback_to_version -------------------------------------------------------


def test_rollback_to_an_older_version_republishes_it_and_appends_a_new_version(
    session: Session, business: Business
):
    _publish(session, business, brand={"name": "Old Name", "tagline": "Old tagline"})
    _publish(session, business, brand={"name": "New Name", "tagline": "New tagline"})
    versions_before = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)
    old_version_id = versions_before[-1].id  # the very first publish

    result = rollback_to_version(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        version_id=old_version_id,
        publisher=FakePublisher(),
    )

    assert result.status is WebsiteStatus.LIVE

    versions_after = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)
    # Rollback is a real publish — it appends a THIRD version, never
    # rewrites or removes either of the first two (P0's "do not delete
    # historical versions" constraint).
    assert len(versions_after) == 3
    assert versions_after[0].is_current is True
    assert versions_after[0].id != old_version_id

    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.LIVE


def test_rollback_for_an_unknown_version_is_rejected(session: Session, business: Business):
    import uuid

    _publish(session, business)

    with pytest.raises(WebsitePublishError) as exc_info:
        rollback_to_version(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            version_id=uuid.uuid4(),
            publisher=FakePublisher(),
        )

    assert exc_info.value.code == "website_version_not_found"


def test_rollback_failure_leaves_the_currently_live_site_reported_live_and_deletes_nothing(
    session: Session, business: Business
):
    live = _publish(session, business)
    versions = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)
    version_id = versions[0].id

    with pytest.raises(WebsitePublishError):
        rollback_to_version(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            version_id=version_id,
            publisher=FakePublisher(fail=True),
        )

    state = get_website_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WebsiteStatus.FAILED  # publish_website's own documented failure behavior
    assert state.live_url == live.live_url  # the site Cloudflare is still actually serving is unaffected

    versions_after = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert len(versions_after) == 1  # nothing was deleted, and a failed rollback appends no new version
    assert versions_after[0].id == version_id


# --- tenant isolation ---------------------------------------------------------


def test_list_versions_never_leaks_across_tenants(session: Session, business: Business, other_tenant: Tenant):
    _publish(session, business)

    versions = list_website_versions(session=session, tenant_id=other_tenant.id, business_id=business.id)

    assert versions == []


def test_rollback_never_crosses_tenants(session: Session, business: Business, other_tenant: Tenant):
    _publish(session, business)
    versions = list_website_versions(session=session, tenant_id=business.tenant_id, business_id=business.id)

    with pytest.raises(WebsitePublishError) as exc_info:
        rollback_to_version(
            session=session,
            tenant_id=other_tenant.id,
            business_id=business.id,
            version_id=versions[0].id,
            publisher=FakePublisher(),
        )

    assert exc_info.value.code == "website_version_not_found"
