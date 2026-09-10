import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import ReviewSource

if TYPE_CHECKING:
    from app.db.models.business import Business


class BusinessReview(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A real, imported/provided customer review — never fabricated
    (Section 4 of the master context: "NEVER fabricate reviews"). `body`
    is stored and displayed verbatim; nothing in this codebase may rewrite
    it. A future Business Analyzer pass extracting recurring customer
    perceptions (e.g. "reliable", "transparent pricing") reads `body`
    across a business's reviews but must never write back into this row —
    insights live on the CreativeBrief the orchestrator builds
    (app.domain.creative.brief), not here.

    `source`+`source_review_id` are unique per business so re-importing
    the same Google review twice is a natural upsert target rather than a
    duplicate row, once real Google import exists — `source_review_id` is
    nullable only for MANUAL reviews entered without one.
    """

    __tablename__ = "business_reviews"
    __table_args__ = (
        UniqueConstraint("business_id", "source", "source_review_id", name="uq_business_reviews_source_review"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[ReviewSource] = mapped_column(str_enum(ReviewSource, 20), nullable=False)
    # Provider-assigned id (e.g. Google's review id) backing the
    # upsert/provenance guarantee above.
    source_review_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    review_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # The raw provider payload, kept verbatim for provenance/audit — never
    # parsed back into body/rating after initial import.
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="reviews")
