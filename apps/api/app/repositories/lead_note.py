from uuid import UUID

from sqlalchemy import select

from app.db.models.lead_note import LeadNote
from app.repositories.base import TenantScopedRepository


class LeadNoteRepository(TenantScopedRepository[LeadNote]):
    model = LeadNote

    def list_for_lead(self, tenant_id: UUID, business_id: UUID, lead_id: UUID) -> list[LeadNote]:
        """Oldest-first (a running log of what's been observed about this
        lead) — scoped to tenant, business, AND lead, same three-way match
        as LeadRepository.get_for_business, so a note can never be listed
        via a lead id that doesn't actually belong to this business."""
        stmt = (
            select(LeadNote)
            .where(
                LeadNote.tenant_id == tenant_id,
                LeadNote.business_id == business_id,
                LeadNote.lead_id == lead_id,
            )
            .order_by(LeadNote.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())
