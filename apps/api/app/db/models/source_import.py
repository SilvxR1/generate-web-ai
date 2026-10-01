import uuid

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import ReviewDecisionKind, SourceImportStatus


class SourceImport(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """R5: one supervised website export (a Higgsfield ZIP an operator
    uploaded) moving through inspection -> review -> build -> preview.

    Identities, never mutated once set for this import:
    - `zip_sha256` / `snapshot_key`: the immutable original in private
      storage (content-addressed; never overwritten);
    - `manifest_sha256` / `manifest_key`: the static SourceManifest;
    - `plan_sha256` / `plan_key`: the current AdaptationPlan (a re-inspection
      after a BusinessTruth change records a NEW plan; approvals bind to one
      plan and never carry over);
    - `business_truth_sha256`: the BusinessTruth the plan was computed from.

    `inspection` is the operator-facing summary (findings, forms, facts,
    origins, build requirements, plan summary) so Studio never has to read
    raw JSON; the raw manifest/plan stay in private storage.
    """

    __tablename__ = "source_imports"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[SourceImportStatus] = mapped_column(str_enum(SourceImportStatus, 30), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    zip_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    zip_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adapter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adapter_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    adapter_contract_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    supportability: Mapped[str | None] = mapped_column(String(40), nullable=True)
    plan_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    business_truth_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    site_origin: Mapped[str] = mapped_column(String(2048), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    inspection: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceReviewDecision(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """R5: an authorized human decision on one REVIEW finding, bound to the
    exact source snapshot and AdaptationPlan it was made for. A decision
    for another snapshot or plan never authorizes a build (see
    app.creative.source_imports.open_reviews). Append-only audit record:
    rows are never updated or deleted by the application."""

    __tablename__ = "source_review_decisions"

    source_import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_imports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_id: Mapped[str] = mapped_column(String(400), nullable=False)
    decision: Mapped[ReviewDecisionKind] = mapped_column(str_enum(ReviewDecisionKind, 20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
