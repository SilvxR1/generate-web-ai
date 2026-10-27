"""Production-readiness checklist (P0 Phase 23-24) — a read-only
synthesis of signals this codebase already computes elsewhere
(Website status, CustomDomain status, whether a BusinessConfig exists,
whether the hosting provider is configured), never a new gate on top of
publishing itself — with one C2.1 exception: the "legal_profile" line is
blocking and mirrors app.publishing.legal_readiness, which refuses to publish
Spanish legal pages that still show facts pending from the owner. POST .../website/publish is untouched by this
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
from app.domain.business_config import BusinessConfig
from app.domain.enums import AssetKind, DomainStatus, LeadSource, WebsiteStatus
from app.publishing.domains import get_custom_domain_state
from app.publishing.legal_readiness import SPANISH_LEGAL_FACTS, spanish_legal_pending_facts
from app.publishing.service import get_website_state
from app.repositories.business import BusinessRepository
from app.repositories.business_asset import BusinessAssetRepository
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

    checks.append(_legal_facts_check(business.config if business is not None else None))

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

    checks.append(_brand_assets_check(session=session, tenant_id=tenant_id, business_id=business_id))
    checks.append(_contact_channels_check(business.config if business is not None else None))

    has_blocking_issues = any(not check.ready and check.blocking for check in checks)
    return ProductionReadinessReport(checks=checks, has_blocking_issues=has_blocking_issues)


def _brand_assets_check(*, session: Session, tenant_id: UUID, business_id: UUID) -> ProductionReadinessCheck:
    """Informational only (LR-06) — a business can publish with no real
    photos/logo (the generator falls back to text, never a fabricated
    image), but the operator should see that plainly rather than
    discover it after publishing. Reuses BusinessAssetRepository, the
    same real, persisted data app.domain.creative.brief already reads —
    never a second source of truth for what assets exist."""
    assets = BusinessAssetRepository(session).list_for_business(tenant_id, business_id)
    has_logo = any(asset.kind is AssetKind.LOGO for asset in assets)
    has_photos = any(asset.kind is AssetKind.IMAGE for asset in assets)

    if has_logo and has_photos:
        detail = "This business has a logo and photos on file."
    elif has_logo:
        detail = (
            "This business has a logo but no photos yet — the generated site will use text/layout only where "
            "photos would help."
        )
    elif has_photos:
        detail = "This business has photos but no logo yet — the generated site will show its name as text instead."
    else:
        detail = (
            "No logo or photos uploaded yet — the generated site will use text/layout only, never a fabricated "
            "image."
        )

    return ProductionReadinessCheck(
        id="brand_assets", label="Brand assets", ready=has_logo and has_photos, blocking=False, detail=detail
    )


def _contact_channels_check(business_config: dict | None) -> ProductionReadinessCheck:
    """Informational only (LR-06) — whether this business's generated
    site can actually capture/receive a lead through *some* real
    channel: the website lead form, WhatsApp, or a configured email
    provider. Reads only real, already-validated BusinessConfig/server
    settings — never claims a channel is active because support for it
    merely exists in this codebase."""
    config = business_config or {}
    lead_management = config.get("lead_management") or {}
    has_lead_form = bool(lead_management.get("enabled")) and "website_form" in (lead_management.get("sources") or [])

    whatsapp = config.get("whatsapp") or {}
    has_whatsapp = bool(whatsapp.get("enabled")) and bool(whatsapp.get("phone_number"))

    has_email_provider = bool(settings.resend_api_key or settings.smtp_host)

    channels = [label for label, active in (("lead form", has_lead_form), ("WhatsApp", has_whatsapp)) if active]
    ready = has_lead_form or has_whatsapp
    if ready:
        detail = f"This business can receive leads via: {', '.join(channels)}."
        if has_email_provider:
            detail += " Lead notifications can be emailed (an email provider is configured on this server)."
    else:
        detail = (
            "No lead-capture channel is configured yet (no website lead form, no WhatsApp) — visitors will have no "
            "way to contact this business through the site."
        )

    return ProductionReadinessCheck(
        id="contact_channels", label="Contact channels", ready=ready, blocking=False, detail=detail
    )


def _legal_facts_check(raw_config: dict | None) -> ProductionReadinessCheck:
    """C2.1: the same rule app.publishing.legal_readiness enforces at publish
    time for the Spanish legal templates every generated site now uses —
    blocking, because a site with pending legal facts can't be published."""
    config = BusinessConfig.model_validate(raw_config) if raw_config else None
    leads = config.lead_management if config else None
    has_form = bool(leads and leads.enabled and LeadSource.WEBSITE_FORM in leads.sources)
    missing = spanish_legal_pending_facts(config, has_contact_form=has_form)
    return ProductionReadinessCheck(
        id="legal_profile",
        label="Legal facts",
        ready=not missing,
        blocking=True,
        detail=(
            "Every fact the legal pages need is provided."
            if not missing
            else "Pending from the business owner: " + "; ".join(SPANISH_LEGAL_FACTS[fact] for fact in missing) + "."
        ),
    )


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
