import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.creative_direction import CreativeDirection
    from app.db.models.website_draft import WebsiteDraft

# Named GenerativeWebsiteArtifact, not WebsiteArtifact, to avoid colliding
# with app.publishing.publisher.WebsiteArtifact — the existing, unrelated,
# transient in-memory build result (`{files: dict[str, bytes],
# entry_point}`) app.publishing.build.build_site already returns for
# every build, deterministic or generative alike. That type is never
# persisted and is a completely different concept from this row (a
# persisted record of *how* a generative build was produced, never the
# built bytes themselves — same "don't persist transient build output"
# reasoning as WebsiteDraft's own docstring).


class GenerativeWebsiteArtifact(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The P2 record of one Generative Frontend Engine run
    (app.creative.frontend_engine) — the implementation-artifact
    counterpart to a CreativeDirection, linked 1:1 to the WebsiteDraft it
    produced (`website_draft_id`, unique). Never duplicates
    WebsiteDraft's own DRAFT -> BUILDING -> READY|BUILD_FAILED -> APPROVED
    -> PUBLISHED lifecycle (app.domain.enums.WebsiteDraftStatus) — that
    state machine still lives entirely on WebsiteDraft, engine-agnostic;
    this row only carries the generative-engine-specific facts a
    DETERMINISTIC draft has no use for (WebsiteDraft.site_config is the
    deterministic engine's equivalent "how this was produced" record).

    `workspace_key` points at the isolated, per-generation workspace
    directory (app.creative.frontend_engine.workspace) the AI Frontend
    Engineer wrote files into and `astro build` ran against — a relative
    path under that module's controlled root, never an absolute path
    trusted from anywhere else, and the directory itself is transient
    (cleaned up after a successful build, same as
    app.publishing.build._BUILD_SCRATCH_DIR): this column is a
    reproducibility/debugging trail (which workspace produced this
    artifact, for a run whose logs are still around), not a promise the
    directory still exists.
    """

    __tablename__ = "generative_website_artifacts"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_drafts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    creative_direction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creative_directions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    framework: Mapped[str] = mapped_column(String(50), nullable=False, default="astro")
    workspace_key: Mapped[str] = mapped_column(String(300), nullable=False)
    build_command: Mapped[str] = mapped_column(String(300), nullable=False)
    output_dir: Mapped[str] = mapped_column(String(300), nullable=False)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    platform_contract_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # app.qa.platform_contract.PlatformContractResult.model_dump(mode="json")
    # — the full QA outcome (blocking_violations/advisory_findings), not
    # only a pass/fail bit, so a human/Studio can see exactly why a draft
    # is BUILD_FAILED or carries validation_issues.
    qa_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generator_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    generator_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="generative_website_artifacts")
    website_draft: Mapped["WebsiteDraft"] = relationship(back_populates="generative_artifact")
    creative_direction: Mapped["CreativeDirection | None"] = relationship(
        back_populates="generative_website_artifacts"
    )
