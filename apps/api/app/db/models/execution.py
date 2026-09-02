import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import ExecutionStatus, ExecutionType

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.website import Website
    from app.db.models.workflow import Workflow


class Execution(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One run of a Workflow, or one Website build. Exactly one of
    workflow_id/website_id is set, matching `type` — enforced at the
    database level via CHECK, not just in application code, since this
    table is the backbone of the "why did client X's workflow fail"
    observability requirement (Section 14) and must stay trustworthy even
    if a future caller bypasses the Pydantic layer."""

    __tablename__ = "executions"
    __table_args__ = (
        CheckConstraint(
            "(type = 'workflow_run' AND workflow_id IS NOT NULL AND website_id IS NULL) OR "
            "(type = 'website_build' AND website_id IS NOT NULL AND workflow_id IS NULL)",
            name="ck_executions_target_matches_type",
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("websites.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[ExecutionType] = mapped_column(str_enum(ExecutionType, 20), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        str_enum(ExecutionStatus, 20), nullable=False, default=ExecutionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_execution_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="executions")
    workflow: Mapped["Workflow | None"] = relationship(back_populates="executions")
    website: Mapped["Website | None"] = relationship(back_populates="executions")
