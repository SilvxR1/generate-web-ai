import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import DomainStatus

if TYPE_CHECKING:
    from app.db.models.business import Business


class CustomDomain(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """At most one per Business (P0 Phase 11-15) — same "unique constraint
    encodes it, not application code" shape as Website.business_id.
    Attaching/detaching goes through app.publishing.domains, which is the
    only code that talks to a real DomainProvider (app.publishing.
    domain_provider) — this row is always a *persisted snapshot* of the
    provider's last-known state, never touched directly by a router.

    This app never purchases or registers a domain on anyone's behalf —
    `domain` must already be owned by the business and pointed at
    Cloudflare Pages by the human themselves (see Studio's own copy on
    the attach form). `status` starts PENDING_VERIFICATION and only
    becomes ACTIVE once a real CloudflarePagesDomainProvider response
    says so; REMOVED mirrors WebsiteStatus.INACTIVE's "was real, now
    turned off, row kept" shape rather than a hard delete.
    """

    __tablename__ = "custom_domains"
    __table_args__ = (UniqueConstraint("business_id", name="uq_custom_domains_business_id"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[DomainStatus] = mapped_column(
        str_enum(DomainStatus, 30), nullable=False, default=DomainStatus.PENDING_VERIFICATION
    )
    # Cloudflare's own raw status string for this hostname, kept verbatim
    # for transparency/debugging — never reinterpreted into a fake
    # certainty this codebase doesn't actually have about Cloudflare's
    # internal state machine (see DomainStatus's own docstring).
    provider_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # What the human must point a CNAME record at — computed, never a
    # credential; safe to read back as-is (see CloudflarePagesDomainProvider).
    cname_target: Mapped[str | None] = mapped_column(String(253), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(back_populates="custom_domain")
