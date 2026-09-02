import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import LeadStatus

if TYPE_CHECKING:
    from app.db.models.business import Business


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A real lead captured through the lead.submitted -> WorkflowConfig
    -> n8n -> /internal/leads loop (see app.routers.internal_automation).
    Deliberately minimal — not a CRM: `status` (NEW -> CONTACTED ->
    WON/LOST) is the only follow-up field; no notes, no pipeline stages,
    no user assignment."""

    __tablename__ = "leads"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Free text, not an enum — mirrors LeadSource's values
    # (app.domain.enums) without importing the domain layer into
    # persistence (Section 2's boundary, same reasoning as
    # Business.config).
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Unlike `source` above, this one *is* an enum column (str_enum,
    # same as Business.status/Website.status): a lead's status is a
    # closed, code-owned vocabulary — never free text a caller could put
    # anything into. Every lead starts here; only PATCH
    # /businesses/{id}/leads/{id}/status (app.routers.businesses) can
    # move it, and only within the same tenant/business.
    status: Mapped[LeadStatus] = mapped_column(str_enum(LeadStatus, 20), nullable=False, default=LeadStatus.NEW)

    business: Mapped["Business"] = relationship(back_populates="leads")
