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

    Rollback (app.publishing.versions.rollback_to_version) never rewrites
    or removes a WebsiteVersion row. v0.2 S1: an artifact-backed version
    (artifact_sha256 set) is restored by redeploying its exact stored,
    integrity-verified artifact — never rebuilt — and the rollback is
    recorded as a NEW version (rolled_back_from_version_id). Only
    historical rows without artifact provenance use the legacy
    SiteConfig rebuild, which is not exact-byte. A failed rollback leaves
    the live Website state untouched and records no version.
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
    # A8.3.4.1 traceability: which WebsiteDraft (if any) this version was
    # promoted from, and the canonical SHA-256 of the exact artifact that
    # was deployed. v0.2 S1: set on every new version (draft promotions,
    # stored direct publishes, rollbacks); null only on historical rows
    # recorded before artifacts existed, which alone use the legacy
    # SiteConfig rebuild (see app.publishing.versions). SET NULL: deleting a
    # draft never deletes history; `artifact_key` below locates the bytes.
    source_website_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # v0.2 S1: the private-storage key of the exact artifact this version
    # deployed (app.publishing.artifact_store), recorded on the version
    # itself so exact rollback never depends on the source draft still
    # existing. Set on every artifact-backed publish and rollback; null only
    # for historical rows that predate it (never backfilled or fabricated).
    artifact_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # v0.2 S1: set only on a version created BY a rollback — the historical
    # version whose artifact it restored. History is append-only: the
    # restored version itself is never modified.
    rolled_back_from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    business: Mapped["Business"] = relationship()
    website: Mapped["Website | None"] = relationship()
