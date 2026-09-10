import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import HealthStatus

if TYPE_CHECKING:
    from app.db.models.business import Business


class WebsiteHealthCheck(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The *latest* website-health snapshot for one business (P1.4) — one
    row per business (see the unique constraint below), overwritten on
    every check, never a growing history table: "Persist only enough
    recent/latest health state for Studio and operational diagnostics...
    keep retention bounded." A future bounded-retention history table is
    an explicitly deferred extension, not something this table tries to
    be.

    Every sub-check gets its own HealthStatus column rather than a single
    boolean, because "healthy"/"down" alone can't express "never checked
    yet" (UNKNOWN) — see app.monitoring.service for how `overall_status`
    is derived from the four sub-checks (never simply the last one
    computed)."""

    __tablename__ = "website_health_checks"
    __table_args__ = (UniqueConstraint("business_id", name="uq_website_health_checks_business_id"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    overall_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)

    # Which URL/host this check actually ran against (Website.deploy_url
    # or an ACTIVE CustomDomain.domain — see app.monitoring.service) —
    # kept for operator transparency, never a caller-supplied value.
    checked_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    http_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    dns_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)

    tls_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)
    tls_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tls_days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)

    deployment_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)
    deployment_last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    form_status: Mapped[HealthStatus] = mapped_column(str_enum(HealthStatus, 20), nullable=False)

    # A short, sanitized explanation of the worst-failing check, if any —
    # never a raw exception message/stack trace (Section 11's "explain
    # what failed without leaking internals"). Null when overall_status
    # is HEALTHY.
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    business: Mapped["Business"] = relationship()
