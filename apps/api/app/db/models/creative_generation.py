import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import CreativeGenerationStatus, CreativeGenerationType, CreativeLevel, CreativeProviderName

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.business_asset import BusinessAsset


class CreativeGeneration(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One traceable request to a CreativeProvider (app.creative.provider)
    — Section 13 of the master context, the record behind Studio's future
    "Generations: 14 / Estimated creative cost: €23.40" summary.

    `provider` is stored via str_enum (native_enum=False — see
    app.db.models.columns) against CreativeProviderName, the same
    "extensible without a migration" reasoning
    app.db.models.integration.Integration already relies on for
    IntegrationProvider: a future provider (OpenAI, Replicate, Flux) is
    addable to that enum alone.

    `status` never regresses from a terminal state (COMPLETED/FAILED/
    CANCELLED) back to PENDING/RUNNING — enforced by
    app.creative.orchestrator, not a DB constraint, since a CHECK can't
    cleanly express "never transition backward" here. `credits_used`/
    `estimated_cost` stay null unless the provider actually reports them
    — Section 13's explicit "do not invent costs" rule.
    """

    __tablename__ = "creative_generations"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[CreativeProviderName] = mapped_column(str_enum(CreativeProviderName, 30), nullable=False)
    generation_type: Mapped[CreativeGenerationType] = mapped_column(
        str_enum(CreativeGenerationType, 30), nullable=False
    )
    creative_level: Mapped[CreativeLevel] = mapped_column(str_enum(CreativeLevel, 20), nullable=False)
    status: Mapped[CreativeGenerationStatus] = mapped_column(
        str_enum(CreativeGenerationStatus, 20), nullable=False, default=CreativeGenerationStatus.PENDING
    )
    # Provider-side identifier for this generation job/asset (e.g. a
    # Higgsfield job id) — opaque to this codebase, never a credential.
    external_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    credits_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # A8.2.4: the normalized WebsiteCreativeDirection v1 (app.domain.
    # creative.website_direction) this generation produced — presentation
    # decisions only, stored exactly as the canonical JSON contract
    # (including `version`). Distinct from generation_metadata, which is
    # free-form provider bookkeeping. NULL when the provider produced no
    # direction (every non-internal provider today, and every generation
    # recorded before A8.2.4 — never backfilled or reconstructed).
    # Written once by app.creative.orchestrator; a WebsiteDraft reaches it
    # through its own creative_generation_id.
    website_direction: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="creative_generations")
    produced_assets: Mapped[list["BusinessAsset"]] = relationship(back_populates="generation")

    @validates("website_direction")
    def _website_direction_is_write_once(self, key: str, value: dict | None) -> dict | None:
        """A recorded direction is a historical result: normal application
        code may set it once (None -> direction) but never overwrite or
        clear it, so a draft built from this generation stays explainable."""
        current = self.__dict__.get(key)
        if current is not None and value != current:
            raise ValueError("CreativeGeneration.website_direction is immutable once recorded.")
        return value
