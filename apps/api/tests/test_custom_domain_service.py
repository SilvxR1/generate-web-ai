"""attach_custom_domain/get_custom_domain_state/refresh_custom_domain_status/
detach_custom_domain (app.publishing.domains) against a fake
DomainProvider and a real (sqlite, in-memory) session: attach requires a
live website, is idempotent for the same domain, rejects a second
different domain without detaching first, a provider failure never
destroys the previously-attached domain's state, detach calls the real
provider (never just a local flag flip) and is idempotent, and tenant
isolation.

Reuses test_website_publish_service.py's FakePublisher/fake build to get
a business into a LIVE website state cheaply — these tests are about the
custom-domain boundary itself, not website publishing (already covered
there) or Cloudflare's wire protocol (see
test_cloudflare_domain_provider.py)."""

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.enums import DomainStatus
from app.publishing.domain_provider import DomainAttachmentResult, DomainProvider
from app.publishing.domains import (
    CustomDomainError,
    attach_custom_domain,
    detach_custom_domain,
    get_custom_domain_state,
    refresh_custom_domain_status,
)
from app.publishing.errors import WebsitePublisherError
from app.publishing.service import publish_website
from tests.test_website_publish_service import _FAKE_ARTIFACT, FakePublisher, _site_config


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    # Same fake-build swap test_website_publish_service.py's own autouse
    # fixture does — an autouse fixture defined in that module doesn't
    # apply here just because this file imports names from it, and these
    # tests are about the custom-domain boundary, not build fidelity.
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: _FAKE_ARTIFACT)


class FakeDomainProvider(DomainProvider):
    def __init__(self, *, fail: bool = False, active_on_attach: bool = False) -> None:
        self.fail = fail
        self.active_on_attach = active_on_attach
        self.attach_calls: list[tuple[str, str]] = []
        self.get_status_calls: list[tuple[str, str]] = []
        self.detach_calls: list[tuple[str, str]] = []

    def attach(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        self.attach_calls.append((site_id, domain))
        if self.fail:
            raise WebsitePublisherError("provider rejected the domain")
        return DomainAttachmentResult(
            domain=domain,
            provider_status="active" if self.active_on_attach else "pending_dcv",
            is_active=self.active_on_attach,
            cname_target=f"{site_id}.pages.dev",
        )

    def get_status(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        self.get_status_calls.append((site_id, domain))
        if self.fail:
            raise WebsitePublisherError("provider status check failed")
        return DomainAttachmentResult(
            domain=domain, provider_status="active", is_active=True, cname_target=f"{site_id}.pages.dev"
        )

    def detach(self, *, site_id: str, domain: str) -> None:
        self.detach_calls.append((site_id, domain))
        if self.fail:
            raise WebsitePublisherError("provider rejected the detach")


def _publish_live_website(session: Session, business: Business) -> None:
    publish_website(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        site_config=_site_config(),
        publisher=FakePublisher(),
    )


# --- attach -----------------------------------------------------------------


def test_attach_requires_a_live_website_first(session: Session, business: Business):
    with pytest.raises(CustomDomainError) as exc_info:
        attach_custom_domain(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            domain="example.com",
            provider=FakeDomainProvider(),
        )

    assert exc_info.value.code == "website_not_live"


def test_attach_persists_the_pending_state(session: Session, business: Business):
    _publish_live_website(session, business)
    provider = FakeDomainProvider()

    result = attach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, domain="example.com", provider=provider
    )

    assert result.domain == "example.com"
    assert result.status is DomainStatus.PENDING_VERIFICATION
    assert result.cname_target == f"site-{business.id.hex}.pages.dev"
    assert provider.attach_calls == [(f"site-{business.id.hex}", "example.com")]

    reloaded = get_custom_domain_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert reloaded is not None
    assert reloaded.domain == "example.com"


def test_attach_reports_active_when_the_provider_says_so_immediately(session: Session, business: Business):
    _publish_live_website(session, business)

    result = attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(active_on_attach=True),
    )

    assert result.status is DomainStatus.ACTIVE
    assert result.verified_at is not None


def test_attach_is_idempotent_for_the_same_domain(session: Session, business: Business):
    _publish_live_website(session, business)
    provider = FakeDomainProvider()
    attach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, domain="example.com", provider=provider
    )

    attach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, domain="example.com", provider=provider
    )

    assert len(provider.attach_calls) == 2


def test_attach_rejects_a_second_different_domain_without_detaching_first(session: Session, business: Business):
    _publish_live_website(session, business)
    provider = FakeDomainProvider()
    attach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, domain="example.com", provider=provider
    )

    with pytest.raises(CustomDomainError) as exc_info:
        attach_custom_domain(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            domain="other.com",
            provider=provider,
        )

    assert exc_info.value.code == "custom_domain_already_attached"


def test_attach_failure_is_reported_and_marks_error(session: Session, business: Business):
    _publish_live_website(session, business)

    with pytest.raises(CustomDomainError) as exc_info:
        attach_custom_domain(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            domain="example.com",
            provider=FakeDomainProvider(fail=True),
        )

    assert exc_info.value.code == "custom_domain_attach_failed"


# --- get / refresh -----------------------------------------------------------


def test_get_custom_domain_state_returns_none_before_any_attach(session: Session, business: Business):
    assert get_custom_domain_state(session=session, tenant_id=business.tenant_id, business_id=business.id) is None


def test_refresh_without_any_prior_attach_is_rejected(session: Session, business: Business):
    with pytest.raises(CustomDomainError) as exc_info:
        refresh_custom_domain_status(
            session=session, tenant_id=business.tenant_id, business_id=business.id, provider=FakeDomainProvider()
        )

    assert exc_info.value.code == "custom_domain_not_found"


def test_refresh_calls_the_provider_for_real_and_updates_the_state(session: Session, business: Business):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )
    refresh_provider = FakeDomainProvider()

    result = refresh_custom_domain_status(
        session=session, tenant_id=business.tenant_id, business_id=business.id, provider=refresh_provider
    )

    assert result.status is DomainStatus.ACTIVE
    assert refresh_provider.get_status_calls == [(f"site-{business.id.hex}", "example.com")]


# --- detach -------------------------------------------------------------------


def test_detach_without_any_prior_attach_is_rejected(session: Session, business: Business):
    with pytest.raises(CustomDomainError) as exc_info:
        detach_custom_domain(
            session=session, tenant_id=business.tenant_id, business_id=business.id, provider=FakeDomainProvider()
        )

    assert exc_info.value.code == "custom_domain_not_found"


def test_detach_calls_the_real_provider_not_just_a_local_flag_flip(session: Session, business: Business):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )
    detach_provider = FakeDomainProvider()

    result = detach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, provider=detach_provider
    )

    assert result.status is DomainStatus.REMOVED
    assert detach_provider.detach_calls == [(f"site-{business.id.hex}", "example.com")]

    reloaded = get_custom_domain_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert reloaded is None  # REMOVED reads back as "nothing attached"


def test_detach_is_idempotent_when_already_removed(session: Session, business: Business):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )
    detach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, provider=FakeDomainProvider()
    )
    second_provider = FakeDomainProvider()

    result = detach_custom_domain(
        session=session, tenant_id=business.tenant_id, business_id=business.id, provider=second_provider
    )

    assert result.status is DomainStatus.REMOVED
    assert second_provider.detach_calls == []  # already removed — must not call the provider again


def test_detach_provider_failure_leaves_the_domain_state_unchanged(session: Session, business: Business):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )

    with pytest.raises(CustomDomainError) as exc_info:
        detach_custom_domain(
            session=session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            provider=FakeDomainProvider(fail=True),
        )

    assert exc_info.value.code == "custom_domain_detach_failed"
    state = get_custom_domain_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is DomainStatus.PENDING_VERIFICATION


# --- tenant isolation ---------------------------------------------------------


def test_tenant_isolation_custom_domain_not_visible_to_another_tenant(
    session: Session, business: Business, other_tenant: Tenant
):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )

    state = get_custom_domain_state(session=session, tenant_id=other_tenant.id, business_id=business.id)

    assert state is None


def test_detach_never_crosses_tenants(session: Session, business: Business, other_tenant: Tenant):
    _publish_live_website(session, business)
    attach_custom_domain(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="example.com",
        provider=FakeDomainProvider(),
    )

    with pytest.raises(CustomDomainError) as exc_info:
        detach_custom_domain(
            session=session, tenant_id=other_tenant.id, business_id=business.id, provider=FakeDomainProvider()
        )

    assert exc_info.value.code == "custom_domain_not_found"
    still_attached = get_custom_domain_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert still_attached is not None
