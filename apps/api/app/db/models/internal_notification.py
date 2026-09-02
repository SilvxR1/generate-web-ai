import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.lead import Lead


class InternalNotification(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The neutral stand-in for "send an internal notification" until a
    real channel (Slack, Teams, ...) is wired up — see
    app.routers.internal_automation. `delivered` is always False right
    now: this table *records* that a notification was due, it never
    pretends one was actually sent anywhere (Section 4's "NO simules
    que Slack ha sido enviado")."""

    __tablename__ = "internal_notifications"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="internal")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    business: Mapped["Business"] = relationship(back_populates="internal_notifications")
    lead: Mapped["Lead | None"] = relationship()
