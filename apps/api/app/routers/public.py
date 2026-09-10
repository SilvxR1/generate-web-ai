"""POST /public/businesses/{business_id}/leads — the one deliberately
anonymous surface in this API (Phase 7). Every other route requires
X-Tenant-Id (app.dependencies.get_current_tenant_id); this one has no
authenticated caller at all — an anonymous website visitor submitting a
customer's real contact form. `tenant_id` is therefore never read from
the request: it's derived from the `Business` row `business_id` resolves
to (BusinessRepository.get_by_id_only — see that method's own docstring
for why this is the one legitimate caller of it), so nothing here lets a
caller submit a lead into an arbitrary tenant.

This exists because the *only* lead-capture path before P0 required n8n
to be configured (lead.submitted -> WorkflowConfig -> n8n ->
POST /internal/leads) — a real first customer's site must work without
that. This endpoint persists the Lead directly and attempts the same
notification/acknowledgement delivery app.notifications.service already
provides, best-effort: a notification/acknowledgement failure never fails
the request or loses the lead (Phase 9 — the lead is always committed
first).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.dependencies import get_optional_notification_sender, get_session, rate_limit_dependency
from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadSource
from app.errors import AppError
from app.leads.spam import is_spam
from app.notifications.sender import NotificationSender
from app.notifications.service import (
    LeadAcknowledgementEmailError,
    NotificationDeliveryError,
    deliver_internal_notification,
    deliver_lead_acknowledgement_email,
)
from app.repositories.business import BusinessRepository
from app.repositories.internal_notification import InternalNotificationRepository
from app.repositories.lead import LeadRepository
from app.schemas.public import PublicLeadCreateRequest, PublicLeadCreateResponse

router = APIRouter(prefix="/public/businesses/{business_id}", tags=["public"])


@router.post("/leads", response_model=PublicLeadCreateResponse, status_code=status.HTTP_201_CREATED)
def create_public_lead(
    business_id: UUID,
    payload: PublicLeadCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
    sender: NotificationSender | None = Depends(get_optional_notification_sender),
    _rate_limit: None = Depends(
        rate_limit_dependency(key_prefix="public_lead", limit_attr="public_lead_rate_limit_per_minute")
    ),
) -> PublicLeadCreateResponse:
    del request  # rate_limit_dependency already reads this for the client IP; nothing else here needs it.

    business = BusinessRepository(session).get_by_id_only(business_id)
    if business is None:
        raise AppError("Business not found.", code="business_not_found", status_code=status.HTTP_404_NOT_FOUND)

    business_config: BusinessConfig | None = None
    if business.config is not None:
        business_config = BusinessConfig.model_validate(business.config)
        if not business_config.lead_management.enabled:
            raise AppError(
                "This business is not currently accepting messages.",
                code="lead_capture_disabled",
                status_code=status.HTTP_403_FORBIDDEN,
            )

    if is_spam(honeypot_value=payload.company_website, rendered_at=payload.rendered_at, now=datetime.now(UTC)):
        # Never tell a bot its submission was rejected — that only
        # teaches it to iterate. The lead is simply never created; the
        # caller sees the exact same response as a real success.
        return PublicLeadCreateResponse()

    lead = Lead(
        tenant_id=business.tenant_id,
        business_id=business.id,
        source=LeadSource.WEBSITE_FORM.value,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        message=payload.message,
        subject=payload.subject,
        source_url=payload.source_url,
        consent_given=payload.consent,
    )
    LeadRepository(session).add(lead)

    # Best-effort from here on — the lead above is already persisted
    # (this function's transaction commits on return, see
    # app.dependencies.get_session), so nothing below can lose it.
    notification = InternalNotification(
        tenant_id=business.tenant_id,
        business_id=business.id,
        lead_id=lead.id,
        channel="internal",
        source="public_lead_form",
        summary=f"New lead from {lead.name or lead.email or lead.phone or 'the website'}.",
    )
    InternalNotificationRepository(session).add(notification)

    try:
        deliver_internal_notification(
            notification=notification, business_name=business.name, business_config=business_config, sender=sender
        )
    except NotificationDeliveryError:
        pass  # notification.delivered stays False; the lead itself is unaffected.

    try:
        deliver_lead_acknowledgement_email(
            lead=lead, business_name=business.name, business_config=business_config, sender=sender
        )
    except LeadAcknowledgementEmailError:
        pass

    return PublicLeadCreateResponse()
