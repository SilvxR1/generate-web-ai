import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import ConfigOrigin, WorkflowVersionStatus

if TYPE_CHECKING:
    from app.db.models.template import Template
    from app.db.models.user import User
    from app.db.models.workflow import Workflow


class WorkflowVersion(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """One immutable snapshot of a Workflow's step definition (what the
    architecture calls WorkflowConfig). `version` is a monotonically
    increasing integer per workflow, not a timestamp, so ordering and
    "which one is active" stay unambiguous."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),)

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[ConfigOrigin] = mapped_column(str_enum(ConfigOrigin, 10), nullable=False)
    status: Mapped[WorkflowVersionStatus] = mapped_column(
        str_enum(WorkflowVersionStatus, 20),
        nullable=False,
        default=WorkflowVersionStatus.DRAFT,
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped["Workflow"] = relationship(back_populates="versions")
    template: Mapped["Template | None"] = relationship(back_populates="workflow_versions")
    approved_by: Mapped["User | None"] = relationship()
