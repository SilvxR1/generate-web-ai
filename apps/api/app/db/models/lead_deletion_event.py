import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import LeadDeletionReason


class LeadDeletionEvent(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """P1: the append-only record that a lead was deleted — who/what deleted
    it, when and why — WITHOUT any of the visitor's personal data: no name,
    email, phone, message, details or page URL. `lead_id` is no foreign key
    (the lead is gone); unique per business, so a retried deletion finds its
    earlier record instead of writing a second one. Never updated or deleted
    by the application (a business hard delete cascades it with everything
    else of that business)."""

    __tablename__ = "lead_deletion_events"
    __table_args__ = (UniqueConstraint("business_id", "lead_id", name="uq_lead_deletion_events_business_lead"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reason: Mapped[LeadDeletionReason] = mapped_column(str_enum(LeadDeletionReason, 30), nullable=False)
    # The operator who deleted it; None for the retention job.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    lead_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notifications_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
