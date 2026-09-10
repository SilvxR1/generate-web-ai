"""Request/response shapes for /internal/leads and /internal/notifications
(app.routers.internal_automation) — the endpoints n8n calls back into.

Both request schemas use extra="ignore" rather than this codebase's
usual extra="forbid": the request body is *forwarded* from an n8n node
(the raw webhook payload for /internal/leads; /internal/leads' own
response, re-forwarded, for /internal/notifications — see
app.automation.n8n.translator._internal_callback_node), which may
legitimately carry fields (e.g. `created_at`, `id`) this schema doesn't
need. Rejecting those would make the integration brittle to exactly the
shape the translator is designed to produce.

LeadResponse is shared by POST /internal/leads (a lead just stored,
always NEW) and GET /internal/leads/{id} (a lead's *current* row,
looked up fresh after a follow-up wait) — one shape for "here is what a
lead currently looks like", not two.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import LeadStatus, NotificationDeliveryStatus


class LeadIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: uuid.UUID
    business_id: uuid.UUID
    source: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    source: str
    name: str | None
    email: str | None
    phone: str | None
    message: str | None
    status: LeadStatus
    acknowledgement_status: NotificationDeliveryStatus
    created_at: datetime


class NotificationIngestRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tenant_id: uuid.UUID
    business_id: uuid.UUID
    source: str
    id: uuid.UUID | None = None  # the originating Lead's id, when this notification is about one
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    message: str | None = None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    lead_id: uuid.UUID | None
    channel: str
    source: str
    summary: str
    delivered: bool
    status: NotificationDeliveryStatus
    created_at: datetime


class LeadFollowUpEmailRequest(BaseModel):
    """Body for POST /internal/leads/{id}/follow-up-email. No email or
    content here — the recipient and the lead's current status are both
    re-derived server-side from the lead's own row (never trusted from
    the request), and the message is fixed for this MVP. `extra="ignore"`
    matches the other n8n-forwarded request schemas in this module."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: uuid.UUID
    business_id: uuid.UUID


class LeadFollowUpEmailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sent: bool


class LeadAcknowledgementEmailRequest(BaseModel):
    """Body for POST /internal/leads/{id}/acknowledgement-email — the
    email.send action's real send (see app.automation.n8n.translator),
    replacing what used to be n8n's own native emailSend/SMTP node. Same
    shape and reasoning as LeadFollowUpEmailRequest above: no email or
    content here, the recipient is re-derived server-side from the
    lead's own row."""

    model_config = ConfigDict(extra="ignore")

    tenant_id: uuid.UUID
    business_id: uuid.UUID


class LeadAcknowledgementEmailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sent: bool
