"""C2.1 — refuse a commercial publication while the Spanish legal pages
still show pending facts.

packages/website-generator's legal-es.ts renders a missing NIF, address,
legal holder, contact email, retention period or legal basis as an explicit
"pending" marker rather than inventing it. This module mirrors that exact
list (SPANISH_LEGAL_FACTS / spanishLegalPendingFacts) so a site carrying any
marker can be built, previewed and reviewed, but never published.

Scope: only a SiteConfig rendered with the Spanish templates
(`locale == "es"`). Rollback is never blocked — restoring a version that was
already live is an incident tool, not a new publication.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.business_config import BusinessConfig
from app.errors import AppError
from app.repositories.business import BusinessRepository

# Stable ids, identical to legal-es.ts's SpanishLegalFact.
SPANISH_LEGAL_FACTS: dict[str, str] = {
    "legal_name": "legal_profile.legal_name (titular)",
    "tax_id": "legal_profile.tax_id (NIF)",
    "address": "legal_profile.address (domicilio)",
    "contact_email": "legal_profile.privacy_contact_email or business_profile.contact.email",
    "data_retention": "legal_profile.data_retention (plazo de conservación)",
    "legal_basis": "lead_management.consent_required (base jurídica del formulario)",
}


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def spanish_legal_pending_facts(config: BusinessConfig | None, *, has_contact_form: bool) -> list[str]:
    legal = config.legal_profile if config else None
    profile = config.business_profile if config else None
    missing: list[str] = []
    if not (legal and _present(legal.legal_name)):
        missing.append("legal_name")
    if not (legal and _present(legal.tax_id)):
        missing.append("tax_id")
    address = legal.address if legal else None
    address_parts = (
        [address.street_address, address.postal_code, address.locality, address.region, address.country]
        if address
        else []
    )
    if not any(_present(part) for part in address_parts):
        missing.append("address")
    contact_email = profile.contact.email if profile and profile.contact else None
    if not ((legal and legal.privacy_contact_email) or _present(contact_email)):
        missing.append("contact_email")
    if has_contact_form:
        if not (legal and _present(legal.data_retention)):
            missing.append("data_retention")
        if not (config and config.lead_management.consent_required):
            missing.append("legal_basis")
    return missing


def site_config_has_contact_form(site_config: dict[str, Any]) -> bool:
    for page in site_config.get("pages") or []:
        for block in page.get("blocks") or []:
            if block.get("type") == "contact" and (block.get("content") or {}).get("form"):
                return True
    return False


def require_legal_facts_for_publication(
    *, session: Session, tenant_id: UUID, business_id: UUID, site_config: dict[str, Any] | None
) -> None:
    """Raises 409 legal_facts_incomplete when `site_config` uses the Spanish
    legal templates and any required fact is still missing."""
    if not site_config or site_config.get("locale") != "es":
        return
    config = _business_config(session, tenant_id, business_id)
    missing = spanish_legal_pending_facts(config, has_contact_form=site_config_has_contact_form(site_config))
    _refuse_if_pending([SPANISH_LEGAL_FACTS[fact] for fact in missing])


def require_legal_facts_for_imported_publication(
    *, session: Session, tenant_id: UUID, business_id: UUID, inspection: dict[str, Any] | None
) -> None:
    """C3: the same rule for a site built from a supervised source import,
    which has no SiteConfig. Its locale and lead forms come from the import's
    stored plan summary (`SourceImport.inspection`, bound to the plan the
    artifact was built from). An import that doesn't record its locale is
    refused, never assumed English. When the business requires consent, every
    imported lead form must carry a consent field: without one the public lead
    route would refuse every submission."""
    site = (inspection or {}).get("site") or {}
    locale = site.get("locale")
    if not locale:
        raise AppError(
            "This imported site doesn't record its language, so its legal pages can't be checked. "
            "Re-inspect and rebuild the import.",
            code="legal_facts_unverifiable",
            status_code=409,
        )
    if locale != "es":
        return
    forms = (inspection or {}).get("forms") or []
    config = _business_config(session, tenant_id, business_id)
    problems = [SPANISH_LEGAL_FACTS[fact] for fact in spanish_legal_pending_facts(config, has_contact_form=bool(forms))]
    if forms and config is not None and config.lead_management.consent_required:
        if not all(any(field.get("role") == "consent" for field in form.get("fields") or []) for form in forms):
            problems.append("a consent checkbox on every contact form (lead_management.consent_required)")
    _refuse_if_pending(problems)


def _business_config(session: Session, tenant_id: UUID, business_id: UUID) -> BusinessConfig | None:
    business = BusinessRepository(session).get(tenant_id, business_id)
    return BusinessConfig.model_validate(business.config) if business and business.config else None


def _refuse_if_pending(problems: list[str]) -> None:
    if problems:
        raise AppError(
            "This site can't be published yet: its legal pages still have facts pending from the business owner ("
            + ", ".join(problems)
            + "). Preview and review stay available.",
            code="legal_facts_incomplete",
            status_code=409,
        )
