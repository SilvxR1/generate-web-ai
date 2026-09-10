from uuid import UUID

from sqlalchemy import select

from app.db.models.website_health import WebsiteHealthCheck
from app.repositories.base import TenantScopedRepository


class WebsiteHealthCheckRepository(TenantScopedRepository[WebsiteHealthCheck]):
    model = WebsiteHealthCheck

    def get_for_business(self, tenant_id: UUID, business_id: UUID) -> WebsiteHealthCheck | None:
        stmt = select(WebsiteHealthCheck).where(
            WebsiteHealthCheck.tenant_id == tenant_id, WebsiteHealthCheck.business_id == business_id
        )
        return self.session.scalars(stmt).first()

    def upsert(self, tenant_id: UUID, business_id: UUID, **fields: object) -> WebsiteHealthCheck:
        """One row per business (P1.4's "latest snapshot only") — updates
        the existing row in place when present, otherwise creates it.
        Never grows into a history table."""
        existing = self.get_for_business(tenant_id, business_id)
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            self.session.flush()
            return existing
        record = WebsiteHealthCheck(tenant_id=tenant_id, business_id=business_id, **fields)
        return self.add(record)
