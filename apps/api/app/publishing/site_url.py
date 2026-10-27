"""C2.1 — the generated site's canonical public origin.

Kept in its own module (not app.publishing.domains, which imports
app.publishing.service) so both build paths can import it without a cycle.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.enums import DomainStatus
from app.repositories.custom_domain import CustomDomainRepository


def canonical_site_url(*, session: Session, tenant_id: UUID, business_id: UUID) -> str | None:
    """ "https://<domain>" for a custom domain the hosting provider reported
    ACTIVE, else None — a canonical URL is never guessed. Read-only, from the
    database row alone (never calls the provider)."""
    custom_domain = CustomDomainRepository(session).get_by_business(tenant_id, business_id)
    if custom_domain is None or custom_domain.status is not DomainStatus.ACTIVE:
        return None
    return f"https://{custom_domain.domain.strip().lower().rstrip('.')}"
