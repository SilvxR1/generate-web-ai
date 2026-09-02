import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import BusinessVertical, TemplateKind


class TemplateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TemplateKind
    # None = generic/all verticals (Section 15's reuse goal), not "unset".
    vertical: BusinessVertical | None = None
    definition: dict[str, Any]
    usage_count: int = Field(default=0, ge=0)

    @field_validator("definition")
    @classmethod
    def _definition_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("definition must not be empty")
        return value


class TemplateCreate(TemplateBase):
    tenant_id: uuid.UUID


class TemplateRead(TemplateBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
