import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.website import Website


class WebsiteVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """An append-only, immutable snapshot of one successful publish (P0
    Phase 20-22) — never updated after creation, never deleted by
    anything this codebase does. app.publishing.service.publish_website
    creates exactly one of these on every successful publish, right
    after it updates the live Website row, so every publish (including
    the republish a rollback itself performs — see
    app.publishing.rollback) accumulates history automatically without
    a second, parallel bookkeeping path.

    Rollback (app.publishing.rollback.rollback_to_version) never rewrites
    or removes a WebsiteVersion row: it reads one back and republishes
    its `site_config` through the exact same publish_website() a normal
    publish uses, which — on failure — is already proven (see
    test_website_publish_service.py) to leave the current live Website
    state untouched. That is what makes "rollback failure must not
    destroy current production, and must never delete historical
    versions" hold by construction rather than by a special case here.
    """

    __tablename__ = "website_versions"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE: a Website row can in principle be deleted
    # and recreated (e.g. a fresh publish after the business itself
    # persists) without this historical record disappearing — mirrors
    # WebsiteDraft.published_website_id's own reasoning.
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The exact SiteConfigPayload this version was built from — what a
    # rollback to this version republishes verbatim, the same "never
    # drift" guarantee app.schemas.site_config.SiteConfigPayload's own
    # docstring already describes for WebsiteDraft.
    site_config: Mapped[dict] = mapped_column(JSON, nullable=False)
    deploy_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider_deployment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    business: Mapped["Business"] = relationship()
    website: Mapped["Website | None"] = relationship()
