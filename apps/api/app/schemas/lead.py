import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import LeadStatus


class LeadRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    source: str
    name: str | None
    email: str | None
    phone: str | None
    message: str | None
    status: LeadStatus
    created_at: datetime


class LeadStatusUpdateRequest(BaseModel):
    """Body for PATCH /businesses/{id}/leads/{id}/status
    (app.routers.businesses) — deliberately the only writable field on a
    Lead from this endpoint; `extra="forbid"` rejects a request that
    tries to smuggle any other field in."""

    model_config = ConfigDict(extra="forbid")

    status: LeadStatus
