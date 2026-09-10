import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import AnalyticsEventType


class AnalyticsEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One consent-gated visitor-behavior event from a generated website
    (P1.7) — deliberately shallow: no session id, no cookie/device
    fingerprint, no IP, no user-agent. `metadata` carries only small,
    non-identifying context (e.g. a WhatsApp CTA's placement:
    "floating"/"contact_section") — see app.schemas.analytics'
    AnalyticsEventCreateRequest for the exact validation that keeps PII
    (names, emails, phone numbers, Lead messages) out of this table
    entirely. Aggregated, never displayed per-row in Studio — see
    app.analytics_events.metrics."""

    __tablename__ = "analytics_events"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[AnalyticsEventType] = mapped_column(str_enum(AnalyticsEventType, 30), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # The submitting page's own path/URL — same "context, never an auth
    # signal" role as Lead.source_url. No default length beyond a plain
    # safety cap; never validated as a real reachable URL (a visitor's
    # browser sends whatever it currently shows).
    source_page: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
