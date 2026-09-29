import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import GenerationFailureKind, GenerationJobStatus


class GenerationJob(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """v0.2 R4: one durable generative-website job — the orchestration
    record the isolated generation worker claims and completes (see
    app.creative.generation_jobs for the state machine). Idempotent per
    (tenant, idempotency_key): re-submitting the same request returns the
    same job instead of a second (paid) generation.

    `input_sha256` pins exactly what the job was asked to build (canonical
    BusinessTruth + request); `error` is a safe summary only.
    """

    __tablename__ = "generation_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_generation_jobs_tenant_key"),)

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[GenerationJobStatus] = mapped_column(
        str_enum(GenerationJobStatus, 20), nullable=False, default=GenerationJobStatus.QUEUED, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_kind: Mapped[GenerationFailureKind | None] = mapped_column(
        str_enum(GenerationFailureKind, 40), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The WebsiteDraft a SUCCEEDED job produced (trusted code created it
    # only after the candidate passed every contract).
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_drafts.id", ondelete="SET NULL"), nullable=True
    )
    # v0.2 R4.1: the job's build input — the generated SOURCE archive in
    # private storage (produced trusted-side; the provider never runs on
    # the execution host) and the public API origin the site calls.
    source_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    api_base_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
