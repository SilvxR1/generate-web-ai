import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    Deliberately does NOT persist the built WebsiteArtifact's HTML/CSS
    bytes — Studio's existing SiteConfigPreview component already renders
    a structural preview directly from `site_config` (no built output
    needed to preview), and publishing re-runs the real `astro build`
    anyway (app.publishing.build.build_site, called again by
    publish_website) — storing a stale copy of transient build output
    would be exactly the kind of over-engineering Phase 6 warns against.

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

    business: Mapped["Business"] = relationship(back_populates="website_drafts")
    creative_generation: Mapped["CreativeGeneration | None"] = relationship()
    published_website: Mapped["Website | None"] = relationship()
    generative_artifact: Mapped["GenerativeWebsiteArtifact | None"] = relationship(
        back_populates="website_draft", uselist=False, cascade="all, delete-orphan"
    )
