from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select

from app.db.models.website import Website
from app.repositories.base import TenantScopedRepository


class WebsiteRepository(TenantScopedRepository[Website]):
    model = Website

    def get_by_business(self, tenant_id: UUID, business_id: UUID) -> Website | None:
        stmt = select(Website).where(Website.tenant_id == tenant_id, Website.business_id == business_id)
        return self.session.scalars(stmt).first()

    def list_for_businesses(self, tenant_id: UUID, business_ids: Sequence[UUID]) -> list[Website]:
        """Batch counterpart to `get_by_business`, for callers that need
        every one of a tenant's Website rows in one query rather than
        one lookup per business (see GET /business-summaries in
        app.routers.businesses, which uses this to avoid an N+1 request
        per business in Studio's dashboard)."""
        if not business_ids:
            return []
        stmt = select(Website).where(Website.tenant_id == tenant_id, Website.business_id.in_(business_ids))
        return list(self.session.scalars(stmt).all())
