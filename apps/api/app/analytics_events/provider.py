"""AnalyticsProvider — the swappable event-ingestion boundary (P1.7).
Mirrors app.notifications.sender.NotificationSender's shape: one small
interface, one concrete implementation for now. InternalAnalyticsProvider
is deliberately the only one — "if a useful internal event collector can
be implemented cheaply and safely, prefer that for the first version...
do NOT introduce an expensive analytics SaaS dependency" — writing
straight to this codebase's own database, no external network call, no
credential, always available."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.analytics_event import AnalyticsEvent
from app.domain.enums import AnalyticsEventType
from app.repositories.analytics_event import AnalyticsEventRepository


class AnalyticsProvider(ABC):
    @abstractmethod
    def record_event(
        self,
        *,
        tenant_id: UUID,
        business_id: UUID,
        event_type: AnalyticsEventType,
        occurred_at: datetime,
        source_page: str | None,
        metadata: dict[str, str] | None,
    ) -> None: ...


class InternalAnalyticsProvider(AnalyticsProvider):
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_event(
        self,
        *,
        tenant_id: UUID,
        business_id: UUID,
        event_type: AnalyticsEventType,
        occurred_at: datetime,
        source_page: str | None,
        metadata: dict[str, str] | None,
    ) -> None:
        event = AnalyticsEvent(
            tenant_id=tenant_id,
            business_id=business_id,
            event_type=event_type,
            occurred_at=occurred_at,
            source_page=source_page,
            event_metadata=metadata,
        )
        AnalyticsEventRepository(self._session).add(event)
