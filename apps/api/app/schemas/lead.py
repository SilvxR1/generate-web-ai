import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import LeadStatus, NotificationDeliveryStatus


class LeadRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    source: str
    name: str | None
    email: str | None
    phone: str | None
    message: str | None
    subject: str | None
    source_url: str | None
    consent_given: bool
    status: LeadStatus
    acknowledgement_status: NotificationDeliveryStatus
    created_at: datetime


class LeadStatusUpdateRequest(BaseModel):
    """Body for PATCH /businesses/{id}/leads/{id}/status
    (app.routers.businesses) — deliberately the only writable field on a
    Lead from this endpoint; `extra="forbid"` rejects a request that
    tries to smuggle any other field in."""

    model_config = ConfigDict(extra="forbid")

    status: LeadStatus


class LeadNoteCreateRequest(BaseModel):
    """Body for POST /businesses/{id}/leads/{id}/notes (P1.3) — one plain
    internal note, never a structured activity-timeline entry."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)


class LeadNoteRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    body: str
    created_at: datetime
