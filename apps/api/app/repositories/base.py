from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.mixins import TenantScopedModel


class TenantScopedRepository[ModelT: TenantScopedModel]:
    """Base for every repository except TenantRepository itself. Tenant
    filtering happens here, once, rather than being left to each call
    site to remember — the data-access-layer half of the tenant-isolation
    requirement (the mixin/CHECK-constraint half lives in app.db.models).
    """

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def get(self, tenant_id: UUID, entity_id: UUID) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == entity_id, self.model.tenant_id == tenant_id)
        return self.session.scalars(stmt).first()

    def list(self, tenant_id: UUID, **filters: Any) -> list[ModelT]:
        stmt = select(self.model).where(self.model.tenant_id == tenant_id)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        return list(self.session.scalars(stmt).all())

    def delete(self, tenant_id: UUID, entity_id: UUID) -> bool:
        entity = self.get(tenant_id, entity_id)
        if entity is None:
            return False
        self.session.delete(entity)
        self.session.flush()
        return True
