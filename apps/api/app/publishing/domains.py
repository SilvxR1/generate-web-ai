"""BusinessConfig-adjacent custom-domain lifecycle (P0 Phase 11-15):
attach/check/detach a business's own domain against whatever hosting
provider is already serving its site (DomainProvider — see
app.publishing.domain_provider), persisted in
app.db.models.custom_domain.CustomDomain. Every operation here is an
explicit, human-triggered action (POST/GET/DELETE .../website/domain,
see app.routers.businesses) — nothing in this module runs on its own.

This app never purchases, registers, or mutates DNS for a domain on
anyone's behalf: attach only tells Cloudflare "this hostname should
route to this project" and returns the CNAME target the human must add
at their own DNS provider. A failed attach/detach never destroys the
website itself (see app.publishing.service.publish_website/
unpublish_website, both untouched by this module) — a custom domain is
strictly additive on top of a business's existing *.pages.dev URL.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.custom_domain import CustomDomain
from app.domain.enums import DomainStatus, WebsiteStatus
from app.publishing.domain_provider import DomainAttachmentResult, DomainProvider
from app.publishing.errors import WebsitePublisherError
from app.publishing.service import website_project_name
from app.repositories.custom_domain import CustomDomainRepository
from app.repositories.website import WebsiteRepository
from app.schemas.domain import CustomDomainState


class CustomDomainError(Exception):
    """Raised for every "can't do this, and here's exactly why" case —
    app.routers.businesses maps `code`/`status_code` straight onto the
    HTTP response, same convention as WebsitePublishError."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _to_state(custom_domain: CustomDomain) -> CustomDomainState:
    return CustomDomainState(
        domain=custom_domain.domain,
        status=custom_domain.status,
        provider_status=custom_domain.provider_status,
        cname_target=custom_domain.cname_target,
        error_message=custom_domain.error_message,
        verified_at=custom_domain.verified_at,
        created_at=custom_domain.created_at,
        updated_at=custom_domain.updated_at,
    )


def _apply_result(custom_domain: CustomDomain, result: DomainAttachmentResult) -> None:
    custom_domain.domain = result.domain
    custom_domain.provider_status = result.provider_status
    custom_domain.cname_target = result.cname_target
    custom_domain.error_message = result.error
    custom_domain.status = DomainStatus.ACTIVE if result.is_active else DomainStatus.PENDING_VERIFICATION
    if result.is_active:
        custom_domain.verified_at = datetime.now(UTC)


def attach_custom_domain(
    *, session: Session, tenant_id: UUID, business_id: UUID, domain: str, provider: DomainProvider
) -> CustomDomainState:
    """Idempotent for the same domain (re-running this is how a human
    checks progress before Studio's own refresh action exists to do
    that more cheaply) — a *different* domain must be detached first
    rather than silently replaced, so a business never loses track of
    which hostname it actually asked to attach."""
    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    if website is None or website.status is not WebsiteStatus.LIVE:
        raise CustomDomainError(
            "Publish this business's website before attaching a custom domain.",
            code="website_not_live",
            status_code=409,
        )

    repo = CustomDomainRepository(session)
    custom_domain = repo.get_by_business(tenant_id, business_id)
    if custom_domain is not None and custom_domain.status is not DomainStatus.REMOVED:
        if custom_domain.domain != domain:
            raise CustomDomainError(
                f"This business already has {custom_domain.domain!r} attached — "
                "detach it before adding a different domain.",
                code="custom_domain_already_attached",
                status_code=409,
            )

    try:
        result = provider.attach(site_id=website_project_name(business_id), domain=domain)
    except WebsitePublisherError as exc:
        if custom_domain is None:
            custom_domain = CustomDomain(tenant_id=tenant_id, business_id=business_id, domain=domain)
            repo.add(custom_domain)
        custom_domain.status = DomainStatus.ERROR
        custom_domain.error_message = str(exc)
        raise CustomDomainError(
            f"Attaching this domain failed: {exc}", code="custom_domain_attach_failed", status_code=502
        ) from exc

    if custom_domain is None:
        custom_domain = CustomDomain(tenant_id=tenant_id, business_id=business_id, domain=domain)
        repo.add(custom_domain)
    _apply_result(custom_domain, result)
    return _to_state(custom_domain)


def get_custom_domain_state(*, session: Session, tenant_id: UUID, business_id: UUID) -> CustomDomainState | None:
    """Read-only, provider-neutral, never touches the hosting provider —
    same convention as app.publishing.service.get_website_state. Returns
    None when this business has never attached a custom domain."""
    custom_domain = CustomDomainRepository(session).get_by_business(tenant_id, business_id)
    if custom_domain is None or custom_domain.status is DomainStatus.REMOVED:
        return None
    return _to_state(custom_domain)


def refresh_custom_domain_status(
    *, session: Session, tenant_id: UUID, business_id: UUID, provider: DomainProvider
) -> CustomDomainState:
    """Re-checks the provider for real — what Studio's "check status"
    action calls after the human has had time to add the CNAME record
    attach's response told them to."""
    custom_domain = CustomDomainRepository(session).get_by_business(tenant_id, business_id)
    if custom_domain is None or custom_domain.status is DomainStatus.REMOVED:
        raise CustomDomainError(
            "This business has no custom domain attached.", code="custom_domain_not_found", status_code=404
        )

    try:
        result = provider.get_status(site_id=website_project_name(business_id), domain=custom_domain.domain)
    except WebsitePublisherError as exc:
        custom_domain.status = DomainStatus.ERROR
        custom_domain.error_message = str(exc)
        raise CustomDomainError(
            f"Checking this domain's status failed: {exc}", code="custom_domain_status_check_failed", status_code=502
        ) from exc

    _apply_result(custom_domain, result)
    return _to_state(custom_domain)


def detach_custom_domain(
    *, session: Session, tenant_id: UUID, business_id: UUID, provider: DomainProvider
) -> CustomDomainState:
    """Takes the domain off the hosting provider for real (never just a
    local status flip — same principle as
    app.publishing.service.unpublish_website), then marks the row
    REMOVED rather than deleting it. Idempotent: a business with no
    custom domain (or one already REMOVED) has nothing further to do —
    returns cleanly instead of raising, except the true "never had one"
    case, which is a 404 the same way unpublish_website's "never
    published" case is."""
    custom_domain = CustomDomainRepository(session).get_by_business(tenant_id, business_id)
    if custom_domain is None:
        raise CustomDomainError(
            "This business has no custom domain attached.", code="custom_domain_not_found", status_code=404
        )
    if custom_domain.status is DomainStatus.REMOVED:
        return _to_state(custom_domain)

    try:
        provider.detach(site_id=website_project_name(business_id), domain=custom_domain.domain)
    except WebsitePublisherError as exc:
        raise CustomDomainError(
            f"Detaching this domain failed: {exc}", code="custom_domain_detach_failed", status_code=502
        ) from exc

    custom_domain.status = DomainStatus.REMOVED
    custom_domain.provider_status = None
    custom_domain.cname_target = None
    custom_domain.error_message = None
    return _to_state(custom_domain)
