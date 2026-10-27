from uuid import UUID

from sqlalchemy import select

from app.db.models.internal_notification import InternalNotification
from app.repositories.base import TenantScopedRepository


class InternalNotificationRepository(TenantScopedRepository[InternalNotification]):
    model = InternalNotification

    def first_delivered_for_lead(
        self, tenant_id: UUID, business_id: UUID, lead_id: UUID
    ) -> InternalNotification | None:
        """C2.1: the earliest internal notification about this lead that was
        actually delivered, if any — the at-most-once check for its email."""
        stmt = (
            select(InternalNotification)
            .where(
                InternalNotification.tenant_id == tenant_id,
                InternalNotification.business_id == business_id,
                InternalNotification.lead_id == lead_id,
                InternalNotification.delivered.is_(True),
            )
            .order_by(InternalNotification.created_at)
        )
        return self.session.scalars(stmt).first()
