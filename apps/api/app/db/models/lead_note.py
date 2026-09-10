import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.lead import Lead


class LeadNote(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A simple internal note an operator leaves on a Lead (P1.3) — not a
    CRM activity timeline: one flat, tenant-scoped list, no threads, no
    edit history, no author/user attribution (no real user auth exists
    yet in this codebase — see app.dependencies.get_current_tenant_id's
    own docstring). Cascades with its Lead: deleting a lead's business
    (Business.leads' own cascade) removes its notes too, never orphaning
    them."""

    __tablename__ = "lead_notes"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="notes")
