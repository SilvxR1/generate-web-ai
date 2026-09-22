from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models.tenant_access import TenantAccess


class TenantAccessRepository:
    """The single source of truth for "may this User act as this Tenant"
    (A2) — every tenant-scoped request must pass through `exists()` before
    a caller-supplied tenant id is ever trusted as authorization. Not
    tenant-scoped itself (a grant spans exactly two tenants — the row's
    own `user_id`'s "home" and the `tenant_id` it grants — so there is no
    single tenant to filter by)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, access: TenantAccess) -> TenantAccess:
        self.session.add(access)
        self.session.flush()
        return access

    def exists(self, *, user_id: UUID, tenant_id: UUID) -> bool:
        stmt = select(TenantAccess.id).where(
            TenantAccess.user_id == user_id, TenantAccess.tenant_id == tenant_id
        )
        return self.session.scalars(stmt).first() is not None

    def get(self, *, user_id: UUID, tenant_id: UUID) -> TenantAccess | None:
        stmt = select(TenantAccess).where(
            TenantAccess.user_id == user_id, TenantAccess.tenant_id == tenant_id
        )
        return self.session.scalars(stmt).first()

    def list_for_user(self, user_id: UUID) -> list[TenantAccess]:
        """Every grant this user holds, `.tenant` eager-loaded — the exact
        set GET /auth/me exposes and the ONLY options a Studio tenant
        selector may ever offer (see app.routers.auth)."""
        stmt = (
            select(TenantAccess)
            .where(TenantAccess.user_id == user_id)
            .options(joinedload(TenantAccess.tenant))
        )
        return list(self.session.scalars(stmt).all())
