import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import DeployTarget, WebsiteStatus

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.execution import Execution
    from app.db.models.template import Template


class Website(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """At most one per Business for the MVP (see the architecture's
    WebsiteConfig decision) — the unique constraint on business_id encodes
    that directly rather than relying on application code to enforce it.

    `config` holds the WebsiteConfig snapshot (the shape
    packages/site-config's SiteConfig already defines on the TypeScript
    side) as an opaque JSON blob for now: the AI layer and its Pydantic
    schema for that shape are out of scope for this phase, so this column
    intentionally isn't deep-validated yet.
    """

    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("business_id", name="uq_websites_business_id"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    deploy_target: Mapped[DeployTarget] = mapped_column(
        str_enum(DeployTarget, 20), nullable=False, default=DeployTarget.CLOUDFLARE
    )
    deploy_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    status: Mapped[WebsiteStatus] = mapped_column(
        str_enum(WebsiteStatus, 20), nullable=False, default=WebsiteStatus.DRAFT
    )
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Set by app.publishing.service.publish_website — the provider-side
    # identifier for the live deployment (e.g. a Cloudflare Workers
    # script name) and when that deployment last succeeded. Never a
    # credential; safe to read back in GET .../website. `deployed_at`
    # only advances on a *successful* publish — a failed attempt updates
    # `status` alone, never this.
    provider_deployment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(back_populates="website")
    template: Mapped["Template | None"] = relationship(back_populates="websites")
    executions: Mapped[list["Execution"]] = relationship(back_populates="website", cascade="all, delete-orphan")
