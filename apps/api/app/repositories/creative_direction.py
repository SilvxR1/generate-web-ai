from uuid import UUID

from sqlalchemy import select

from app.db.models.creative_direction import CreativeDirection
from app.repositories.base import TenantScopedRepository


class CreativeDirectionRepository(TenantScopedRepository[CreativeDirection]):
    model = CreativeDirection

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[CreativeDirection]:
        stmt = (
            select(CreativeDirection)
            .where(CreativeDirection.tenant_id == tenant_id, CreativeDirection.business_id == business_id)
            .order_by(CreativeDirection.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, direction_id: UUID) -> CreativeDirection | None:
        stmt = select(CreativeDirection).where(
            CreativeDirection.tenant_id == tenant_id,
            CreativeDirection.business_id == business_id,
            CreativeDirection.id == direction_id,
        )
        return self.session.scalars(stmt).first()

    def list_for_generation(
        self, tenant_id: UUID, business_id: UUID, creative_generation_id: UUID
    ) -> list[CreativeDirection]:
        """Every candidate produced by one create_directions call — what
        the critic (app.creative.critic.select_direction) scores against
        each other, and what Studio's directions panel renders as one
        set of alternatives."""
        stmt = (
            select(CreativeDirection)
            .where(
                CreativeDirection.tenant_id == tenant_id,
                CreativeDirection.business_id == business_id,
                CreativeDirection.creative_generation_id == creative_generation_id,
            )
            .order_by(CreativeDirection.created_at.asc())
        )
        return list(self.session.scalars(stmt).all())
