from uuid import UUID

from sqlalchemy import select

from app.db.models.business import Business
from app.repositories.base import TenantScopedRepository


class BusinessRepository(TenantScopedRepository[Business]):
    model = Business

    def get_by_id_only(self, business_id: UUID) -> Business | None:
        """The one deliberate exception to this codebase's "always scope
        by tenant_id" rule (Section 18) — used exclusively by
        app.routers.public's anonymous lead-submission endpoint, where
        there is no authenticated caller to derive a tenant from in the
        first place. `tenant_id` is read back off the returned row
        itself (never accepted from the request) before anything else
        happens — see that router's own docstring. Not for use by any
        tenant-authenticated route."""
        stmt = select(Business).where(Business.id == business_id)
        return self.session.scalars(stmt).first()
