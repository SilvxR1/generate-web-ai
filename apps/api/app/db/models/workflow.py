import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import WorkflowStatus

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.execution import Execution
    from app.db.models.workflow_version import WorkflowVersion


class Workflow(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A Business can have several (e.g. lead-capture, review-request).
    The actual step-by-step definition lives versioned in WorkflowVersion,
    not here — this row is the stable identity + n8n linkage, and the
    one place an automation's *activation* state persists across
    requests (active/inactive/error, which n8n workflow backs it). See
    app.automation.activation, the only code that writes to it."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("business_id", "local_workflow_id", name="uq_workflows_business_local_workflow_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        str_enum(WorkflowStatus, 20), nullable=False, default=WorkflowStatus.DRAFT
    )
    n8n_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # The domain WorkflowConfig this row tracks (app.domain.workflow_config,
    # e.g. "reforma-casa-valencia-lead-capture") plus the generator
    # version/capabilities it had the last time it was (re)activated —
    # refreshed from BusinessConfig on every activation, so these always
    # describe what's actually running remotely, not just what the
    # current config would generate right now.
    local_workflow_id: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(back_populates="workflows")
    versions: Mapped[list["WorkflowVersion"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowVersion.version"
    )
    executions: Mapped[list["Execution"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
