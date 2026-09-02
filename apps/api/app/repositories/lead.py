from uuid import UUID

from sqlalchemy import select

from app.db.models.lead import Lead
from app.repositories.base import TenantScopedRepository


class LeadRepository(TenantScopedRepository[Lead]):
    model = Lead

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[Lead]:
        """Most-recent-first, scoped to both tenant and business — the
        Studio leads list reads this directly, so ordering lives here
        rather than being left to the caller to remember."""
        stmt = (
            select(Lead)
            .where(Lead.tenant_id == tenant_id, Lead.business_id == business_id)
            .order_by(Lead.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, lead_id: UUID) -> Lead | None:
        """Like the base class's `get`, but also requires `business_id`
        to match — the base version alone would let a caller update a
        lead that belongs to a *different* business owned by the same
        tenant, as long as they knew its id. Used by PATCH
        /businesses/{id}/leads/{id}/status (app.routers.businesses) so
        that endpoint can't cross a business boundary within one tenant,
        not just a tenant boundary."""
        stmt = select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id, Lead.business_id == business_id)
        return self.session.scalars(stmt).first()
