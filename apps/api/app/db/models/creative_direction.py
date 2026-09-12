import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.creative_generation import CreativeGeneration
    from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact


class CreativeDirection(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One persisted candidate (or the selected, deepened) creative
    direction produced by a CreativeDirectorProvider.create_directions/
    develop_direction call (app.creative.director) — the P2 first-class
    domain concept between a CreativeBrief (facts) and a concrete
    frontend implementation (GenerativeWebsiteArtifact).

    `concept`/`visual_language`/`experience`/`content_strategy` store the
    matching nested Pydantic blocks from
    app.domain.creative.direction.CreativeDirection as plain JSON (this
    table has no interest in querying inside them — a caller always
    round-trips the whole row through that Pydantic model, the same
    "JSON column, typed boundary lives in the domain model" pattern
    app.db.models.business.Business.config already uses for
    BusinessConfig). `references_` is named with a trailing underscore
    only to avoid shadowing SQLAlchemy's declarative attribute
    resolution for the reserved-sounding `references`; the domain model's
    own field is plain `references`.

    Linked to the CreativeGeneration that produced it (Section 13-style
    traceability, same shape as WebsiteDraft.creative_generation_id) —
    `SET NULL` on delete, since losing the generation-tracking row must
    never delete a still-useful CreativeDirection a human may have
    already reviewed or selected.
    """

    __tablename__ = "creative_directions"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    creative_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creative_generations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    concept: Mapped[dict] = mapped_column(JSON, nullable=False)
    visual_language: Mapped[dict] = mapped_column(JSON, nullable=False)
    experience: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_strategy: Mapped[dict] = mapped_column(JSON, nullable=False)
    references_: Mapped[list] = mapped_column("references", JSON, nullable=False, default=list)
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False)
    provider_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Set by the critic (app.creative.critic.select_direction) once every
    # candidate from one create_directions call exists — never by the
    # provider that proposed the candidate itself. Exactly one candidate
    # per create_directions batch is recommended; a human can still pick
    # a different one (P2.4's "allow future manual selection from
    # Studio"), which is a router-level concern (which direction gets
    # passed to develop_direction/the frontend engine), not a second flag
    # on this row — `is_recommended` never changes after the critic sets
    # it, regardless of what a human later chooses.
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selection_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    developed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(back_populates="creative_directions")
    creative_generation: Mapped["CreativeGeneration | None"] = relationship()
    generative_website_artifacts: Mapped[list["GenerativeWebsiteArtifact"]] = relationship(
        back_populates="creative_direction"
    )
