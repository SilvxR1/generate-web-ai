import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import WorkflowStatus


class WorkflowBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    status: WorkflowStatus = WorkflowStatus.DRAFT
    n8n_workflow_id: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class WorkflowCreate(WorkflowBase):
    tenant_id: uuid.UUID
    business_id: uuid.UUID


class WorkflowRead(WorkflowBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
