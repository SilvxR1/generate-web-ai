from uuid import UUID

from sqlalchemy import select

from app.db.models.creative_generation import CreativeGeneration
from app.repositories.base import TenantScopedRepository


class CreativeGenerationRepository(TenantScopedRepository[CreativeGeneration]):
    model = CreativeGeneration

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[CreativeGeneration]:
        """Every generation attempt for this business, most recent first
        — the traceability history Section 13 of the master context
        describes. Same tenant+business scoping as every other
        *_for_business lookup in this codebase."""
        stmt = (
            select(CreativeGeneration)
            .where(CreativeGeneration.tenant_id == tenant_id, CreativeGeneration.business_id == business_id)
            .order_by(CreativeGeneration.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(
        self, tenant_id: UUID, business_id: UUID, generation_id: UUID
    ) -> CreativeGeneration | None:
        stmt = select(CreativeGeneration).where(
            CreativeGeneration.tenant_id == tenant_id,
            CreativeGeneration.business_id == business_id,
            CreativeGeneration.id == generation_id,
        )
        return self.session.scalars(stmt).first()
