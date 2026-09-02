from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.tenant import Tenant


class TenantRepository:
    """Not tenant-scoped by definition — this is the root entity every
    other repository scopes against."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def get(self, tenant_id: UUID) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def list(self) -> list[Tenant]:
        return list(self.session.scalars(select(Tenant)).all())
