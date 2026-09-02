import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.enums import ExecutionStatus, ExecutionType


class ExecutionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ExecutionType
    status: ExecutionStatus = ExecutionStatus.PENDING
    workflow_id: uuid.UUID | None = None
    website_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    external_execution_id: str | None = None
    error_summary: str | None = None

    @model_validator(mode="after")
    def _target_matches_type(self) -> "ExecutionBase":
        if self.type == ExecutionType.WORKFLOW_RUN:
            if self.workflow_id is None or self.website_id is not None:
                raise ValueError("workflow_run executions require workflow_id and must not set website_id")
        elif self.type == ExecutionType.WEBSITE_BUILD:
            if self.website_id is None or self.workflow_id is not None:
                raise ValueError("website_build executions require website_id and must not set workflow_id")
        return self

    @model_validator(mode="after")
    def _finished_not_before_started(self) -> "ExecutionBase":
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at must not be before started_at")
        return self


class ExecutionCreate(ExecutionBase):
    tenant_id: uuid.UUID
    business_id: uuid.UUID


class ExecutionRead(ExecutionBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
