"""Production-readiness checklist (P0 Phase 23-24) — a read-only
synthesis of signals this codebase already computes elsewhere
(Website status, CustomDomain status, whether a BusinessConfig exists,
whether the hosting provider is configured), never a new gate on top of
publishing itself. POST .../website/publish is untouched by this
module: the only things that already stop a publish from succeeding are
the same two genuine technical blockers this checklist surfaces (no
website configuration to publish; Cloudflare not configured on this
server — see get_website_publisher's own 503). Every other line here
(legal profile completeness, a custom domain, prior publication) is
informational, `blocking=False`, and must stay that way — P0's explicit
"only real technical blockers should prevent publishing... do NOT
invent legal blocking rules" constraint.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.domain.enums import DomainStatus, WebsiteStatus
from app.publishing.domains import get_custom_domain_state
from app.publishing.service import get_website_state
from app.repositories.business import BusinessRepository
from app.schemas.readiness import ProductionReadinessCheck, ProductionReadinessReport


def get_production_readiness(*, session: Session, tenant_id: UUID, business_id: UUID) -> ProductionReadinessReport:
    business = BusinessRepository(session).get(tenant_id, business_id)
    has_config = business is not None and business.config is not None
    checks = [
        ProductionReadinessCheck(
            id="website_config",
            label="Website configuration",
            ready=has_config,
            blocking=True,
            detail=(
                "This business has a generated website configuration."
                if has_config
                else "No website configuration yet — complete the business proposal first."
            ),
        ),
        _hosting_provider_check(),
    ]

    website = get_website_state(session=session, tenant_id=tenant_id, business_id=business_id)
    is_live = website is not None and website.status is WebsiteStatus.LIVE
    checks.append(
        ProductionReadinessCheck(
            id="published",
            label="Published",
            ready=is_live,
            blocking=False,
            detail="This website is live." if is_live else "This website has not been published yet.",
        )
    )

    legal_profile = (business.config or {}).get("legal_profile") if business is not None else None
    legal_complete = bool(
        legal_profile
        and legal_profile.get("legal_name")
        and legal_profile.get("address")
        and legal_profile.get("privacy_contact_email")
    )
    checks.append(
        ProductionReadinessCheck(
            id="legal_profile",
            label="Legal profile",
            ready=legal_complete,
            blocking=False,
            detail=(
                "Legal name, address, and privacy contact email are filled in."
                if legal_complete
                else "Legal profile is incomplete — the generated legal pages will show \"Not provided\" for "
                "missing fields. This does not block publishing."
            ),
        )
    )

    custom_domain = get_custom_domain_state(session=session, tenant_id=tenant_id, business_id=business_id)
    domain_active = custom_domain is not None and custom_domain.status is DomainStatus.ACTIVE
    checks.append(
        ProductionReadinessCheck(
            id="custom_domain",
            label="Custom domain",
            ready=domain_active,
            blocking=False,
            detail=(
                f"{custom_domain.domain} is active." if domain_active and custom_domain is not None else
                "No active custom domain — the site is reachable at its Cloudflare Pages URL. "
                "This does not block publishing."
            ),
        )
    )

    has_blocking_issues = any(not check.ready and check.blocking for check in checks)
    return ProductionReadinessReport(checks=checks, has_blocking_issues=has_blocking_issues)


def _hosting_provider_check() -> ProductionReadinessCheck:
    configured = bool(settings.cloudflare_account_id and settings.cloudflare_api_token)
    return ProductionReadinessCheck(
        id="hosting_provider",
        label="Hosting provider",
        ready=configured,
        blocking=True,
        detail=(
            "Cloudflare is configured on this server."
            if configured
            else "Cloudflare is not configured on this server — publishing will fail until it is."
        ),
    )
