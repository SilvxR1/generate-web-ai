from uuid import UUID

from sqlalchemy import select

from app.db.models.website import Website
from app.repositories.base import TenantScopedRepository


class WebsiteRepository(TenantScopedRepository[Website]):
    model = Website

    def get_by_business(self, tenant_id: UUID, business_id: UUID) -> Website | None:
        stmt = select(Website).where(Website.tenant_id == tenant_id, Website.business_id == business_id)
        return self.session.scalars(stmt).first()
