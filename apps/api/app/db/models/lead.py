import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import LeadStatus

if TYPE_CHECKING:
    from app.db.models.business import Business


class Lead(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A real lead — captured either through the lead.submitted ->
    WorkflowConfig -> n8n -> /internal/leads loop (see
    app.routers.internal_automation) when n8n is configured, or directly
    through POST /public/businesses/{id}/leads (app.routers.public, P0)
    when it isn't: a real first customer's contact form must work
    without n8n being set up at all. Deliberately still minimal — not a
    CRM: `status` (NEW -> CONTACTED -> QUALIFIED -> WON/LOST) is the only
    follow-up field; no notes, no pipeline stages, no user assignment.
    """

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
    # What service/topic the lead is about — free text, same "not every
    # field is required" shape as name/email/phone/message above.
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Where the submitting page actually was — the public contact form's
    # own URL, for context (which page, which campaign) without needing
    # a heavier analytics system. Never trusted as an auth signal.
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Whether the submitter checked a real consent checkbox on the public
    # form (see app.schemas.public.PublicLeadCreateRequest) — recorded
    # verbatim, never inferred or defaulted to True.
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Free-form provenance only (e.g. which spam check passed) — never a
    # dumping ground for extra PII beyond name/email/phone/message above
    # (Section 6: "Avoid storing unnecessary personal data"). Named
    # lead_metadata, not metadata: `metadata` is a reserved attribute on
    # every SQLAlchemy declarative model (Base.metadata), same reasoning
    # as BusinessAsset.asset_metadata/CreativeGeneration.generation_metadata.
    lead_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Unlike `source` above, this one *is* an enum column (str_enum,
    # same as Business.status/Website.status): a lead's status is a
    # closed, code-owned vocabulary — never free text a caller could put
    # anything into. Every lead starts here; only PATCH
    # /businesses/{id}/leads/{id}/status (app.routers.businesses) can
    # move it, and only within the same tenant/business.
    status: Mapped[LeadStatus] = mapped_column(str_enum(LeadStatus, 20), nullable=False, default=LeadStatus.NEW)

    business: Mapped["Business"] = relationship(back_populates="leads")
