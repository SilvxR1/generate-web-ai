import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import ConfigOrigin, WorkflowVersionStatus


class WorkflowVersionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    # The WorkflowConfig snapshot itself — see the architecture's AI
    # boundary: node types get allow-list-validated by the translator
    # layer (out of scope here), not by this schema.
    definition: dict[str, Any]
    created_by: ConfigOrigin
    status: WorkflowVersionStatus = WorkflowVersionStatus.DRAFT
    approved_by_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    template_id: uuid.UUID | None = None

    @field_validator("definition")
    @classmethod
    def _definition_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("definition must not be empty")
        return value

    @model_validator(mode="after")
    def _approval_requires_approver(self) -> "WorkflowVersionBase":
        if self.status in (WorkflowVersionStatus.APPROVED, WorkflowVersionStatus.PUBLISHED):
            if self.approved_by_id is None or self.approved_at is None:
                raise ValueError(
                    "approved_by_id and approved_at are required once a version is approved or published "
                    "(Section 5: human confirmation is not optional before execution)"
                )
        return self


class WorkflowVersionCreate(WorkflowVersionBase):
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID


class WorkflowVersionRead(WorkflowVersionBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
