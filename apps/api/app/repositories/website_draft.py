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

    def get_for_business(
        self, tenant_id: UUID, business_id: UUID, draft_id: UUID, *, for_update: bool = False
    ) -> WebsiteDraft | None:
        """`for_update=True` takes a row lock (SELECT ... FOR UPDATE on
        Postgres; a no-op on SQLite) — A8.3.4.2a uses it so two concurrent
        Preview clicks for one draft serialize instead of both deploying."""
        stmt = select(WebsiteDraft).where(
            WebsiteDraft.tenant_id == tenant_id,
            WebsiteDraft.business_id == business_id,
            WebsiteDraft.id == draft_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return self.session.scalars(stmt).first()
