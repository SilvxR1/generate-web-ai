import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import GenerationEngine, WebsiteDraftStatus

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.creative_generation import CreativeGeneration
    from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
    from app.db.models.website import Website


class WebsiteDraft(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A safe, pre-publish website output (Phase 6/7 of the Creative
    Orchestrator continuation) — the missing link between a
    CreativeGeneration and the *live* Website row. Publishing a draft
    (app.publishing.drafts.publish_website_draft) reuses the existing
    app.publishing.service.publish_website unchanged; nothing here is a
    second deployment system.

    `site_config` holds the exact SiteConfig payload (the same shape
    Website.config already stores once live — see that model's own
    docstring) so a draft can be approved and published without
    recomputing anything: what a human previewed is exactly what gets
    published, the same "never drift" guarantee
    app.schemas.site_config.SiteConfigPayload's own docstring already
    describes for the live-publish path.

    A8.3.4.1 (build once / promote): the validated build output IS
    persisted now — `artifact_key` names the immutable archive (see
    app.publishing.artifact_store) of the exact WebsiteArtifact that
    passed PlatformContract, and `artifact_sha256` its canonical identity.
    Publish deploys that archive after re-verifying the hash; it never
    rebuilds. Both are null only on legacy drafts created before this
    existed (and on BUILD_FAILED drafts), which Publish refuses. Once set,
    they — and `site_config` — are write-once (see the validators below):
    a draft's source, artifact and identity can never drift apart.

    P2 extension: `engine` (GenerationEngine) decides which of
    `site_config`/`generative_artifact` is populated for this draft —
    `DETERMINISTIC` (the default, and the only value every pre-P2 row
    has) always carries `site_config`; `GENERATIVE` always carries a
    linked GenerativeWebsiteArtifact instead (`site_config` stays null —
    see app.creative.frontend_engine for how a GENERATIVE draft is
    created). The state machine itself
    (DRAFT->BUILDING->READY|BUILD_FAILED->APPROVED->PUBLISHED) is
    identical either way; only *how* READY was reached differs. This is
    still one lifecycle, not two — see app.publishing.drafts's own
    docstring for how the two engines share it.
    """

    __tablename__ = "website_drafts"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: a draft can in principle be created without a tracked
    # CreativeGeneration (e.g. a manual re-save), though every path this
    # phase actually wires up sets it. SET NULL on delete — losing the
    # generation record must never delete a still-valid draft.
    creative_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creative_generations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    engine: Mapped[GenerationEngine] = mapped_column(
        str_enum(GenerationEngine, 20), nullable=False, default=GenerationEngine.DETERMINISTIC
    )
    # Nullable as of P2: null exactly when engine is GENERATIVE (see this
    # model's own docstring) — never both null and un-linked to a
    # GenerativeWebsiteArtifact, enforced in app.publishing.drafts /
    # app.creative.frontend_engine, not by a DB constraint (SQLite's
    # limited CHECK/cross-column support is the same reason
    # WebsiteDraftStatus's terminal-state rule isn't a DB constraint
    # either — see that enum's own docstring).
    site_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[WebsiteDraftStatus] = mapped_column(
        str_enum(WebsiteDraftStatus, 20), nullable=False, default=WebsiteDraftStatus.DRAFT
    )
    build_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # list[str] from app.qa.validate — non-blocking findings a human sees
    # before approving; never prevents a READY draft from being approved
    # (only a BUILD_FAILED one is blocked, since an unbuildable site can
    # never safely go live).
    validation_issues: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only once this draft is actually published — which live Website
    # row it became, for traceability. SET NULL on delete (deleting the
    # Website row must never delete the historical draft record of how it
    # got there).
    published_website_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("websites.id", ondelete="SET NULL"), nullable=True
    )
    # A8.3.4.1: internal StorageProvider key (never a URL) + canonical
    # SHA-256 of the validated artifact. Null on legacy/failed drafts.
    artifact_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A8.3.4.2a real preview: the current preview deployment of the stored
    # artifact (lazy, owner-requested). Expiry is derived:
    # preview_created_at + app.publishing.drafts.PREVIEW_TTL.
    preview_deployment_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    preview_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(back_populates="website_drafts")
    creative_generation: Mapped["CreativeGeneration | None"] = relationship()
    published_website: Mapped["Website | None"] = relationship()
    generative_artifact: Mapped["GenerativeWebsiteArtifact | None"] = relationship(
        back_populates="website_draft", uselist=False, cascade="all, delete-orphan"
    )

    @validates("artifact_key", "artifact_sha256")
    def _artifact_write_once(self, key: str, value: str | None) -> str | None:
        current = getattr(self, key)
        if current is not None and value != current:
            raise ValueError(f"WebsiteDraft.{key} is write-once and already set")
        return value

    @validates("site_config")
    def _site_config_frozen_once_artifact_exists(self, key: str, value: dict | None) -> dict | None:
        if self.artifact_sha256 is not None and value != self.site_config:
            raise ValueError("WebsiteDraft.site_config cannot change once its artifact has been stored")
        return value
