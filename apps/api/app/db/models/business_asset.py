import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.creative_generation import CreativeGeneration


class BusinessAsset(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One real or generated brand/content asset belonging to a Business —
    the reusable asset library Section 14 of the master context describes
    (regenerate a page or campaign six months later using the same
    business identity and previous assets, not disposable single-
    generation context).

    `storage_url` is a plain string, the same deliberate choice as
    app.domain.business_config.brand.AssetRef.url: no upload pipeline or
    object-storage abstraction exists in this codebase yet (Section 2
    explicitly says not to over-engineer storage before one does), so
    this column holds wherever the asset actually lives today (an
    externally-hosted URL, a future storage provider's URL) rather than
    inventing a new storage backend here.

    `origin` records provenance — UPLOADED/IMPORTED for real business
    content, GENERATED (with `generation_id` set) for creative-provider
    output. This is exactly what lets app.domain.creative.brief prefer
    real assets over generated ones for the same category (Section 1:
    "real business content > generated content") without ever needing to
    guess.
    """

    __tablename__ = "business_assets"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind, 20), nullable=False)
    category: Mapped[AssetCategory] = mapped_column(
        str_enum(AssetCategory, 30), nullable=False, default=AssetCategory.OTHER
    )
    origin: Mapped[AssetOrigin] = mapped_column(str_enum(AssetOrigin, 20), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Free-form provenance/classification metadata (e.g. a future
    # AssetClassifier's confidence score, the source platform for an
    # imported asset) — never authoritative on its own; kind/category/
    # origin above are the queryable, code-owned facts.
    asset_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set only when origin == GENERATED: which CreativeGeneration produced
    # this asset (Section 14's "regenerate using previous assets" flow).
    # SET NULL on delete — losing the generation record that produced an
    # asset must never delete the (still real, still usable) asset.
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creative_generations.id", ondelete="SET NULL"), nullable=True
    )

    business: Mapped["Business"] = relationship(back_populates="assets")
    generation: Mapped["CreativeGeneration | None"] = relationship(back_populates="produced_assets")
