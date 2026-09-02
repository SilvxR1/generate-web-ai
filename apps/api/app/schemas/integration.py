import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import IntegrationProvider, IntegrationStatus


class IntegrationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: IntegrationProvider
    status: IntegrationStatus = IntegrationStatus.PENDING
    scopes: list[str] | None = None


class IntegrationCreate(IntegrationBase):
    tenant_id: uuid.UUID
    business_id: uuid.UUID


class IntegrationRead(IntegrationBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
