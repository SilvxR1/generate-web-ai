from uuid import UUID

from sqlalchemy import select

from app.db.models.website_draft import WebsiteDraft
from app.repositories.base import TenantScopedRepository


class WebsiteDraftRepository(TenantScopedRepository[WebsiteDraft]):
    model = WebsiteDraft

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[WebsiteDraft]:
        """Every draft ever created for this business, most recent first
        — same tenant+business scoping as every other *_for_business
        lookup in this codebase (see LeadRepository.list_for_business)."""
        stmt = (
            select(WebsiteDraft)
            .where(WebsiteDraft.tenant_id == tenant_id, WebsiteDraft.business_id == business_id)
            .order_by(WebsiteDraft.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, draft_id: UUID) -> WebsiteDraft | None:
        stmt = select(WebsiteDraft).where(
            WebsiteDraft.tenant_id == tenant_id,
            WebsiteDraft.business_id == business_id,
            WebsiteDraft.id == draft_id,
        )
        return self.session.scalars(stmt).first()
