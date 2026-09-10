from uuid import UUID

from sqlalchemy import select

from app.db.models.custom_domain import CustomDomain
from app.repositories.base import TenantScopedRepository


class CustomDomainRepository(TenantScopedRepository[CustomDomain]):
    model = CustomDomain

    def get_by_business(self, tenant_id: UUID, business_id: UUID) -> CustomDomain | None:
        stmt = select(CustomDomain).where(CustomDomain.tenant_id == tenant_id, CustomDomain.business_id == business_id)
        return self.session.scalars(stmt).first()
