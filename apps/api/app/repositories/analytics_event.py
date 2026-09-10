from datetime import datetime
from uuid import UUID

from sqlalchemy import exists, func, select

from app.db.models.analytics_event import AnalyticsEvent
from app.domain.enums import AnalyticsEventType
from app.repositories.base import TenantScopedRepository


class AnalyticsEventRepository(TenantScopedRepository[AnalyticsEvent]):
    model = AnalyticsEvent

    def has_any_for_business(self, tenant_id: UUID, business_id: UUID) -> bool:
        """Whether analytics has *ever* recorded anything for this
        business — the "no data yet" vs. "a real, known zero" boundary
        app.analytics_events.metrics needs (P1.8: "If data is
        unavailable: show 'No data yet' not zero unless zero is actually
        known")."""
        stmt = select(
            exists().where(AnalyticsEvent.tenant_id == tenant_id, AnalyticsEvent.business_id == business_id)
        )
        return bool(self.session.scalar(stmt))

    def count_in_window(
        self, tenant_id: UUID, business_id: UUID, *, event_type: AnalyticsEventType, since: datetime
    ) -> int:
        stmt = select(func.count()).where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.business_id == business_id,
            AnalyticsEvent.event_type == event_type,
            AnalyticsEvent.occurred_at >= since,
        )
        return int(self.session.scalar(stmt) or 0)
