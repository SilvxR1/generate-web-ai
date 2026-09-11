"""POST /internal/leads, GET /internal/leads/{id}, POST
/internal/leads/{id}/follow-up-email, POST
/internal/leads/{id}/acknowledgement-email, and POST
/internal/notifications — the endpoints app.automation.n8n.translator's
lead.store/lead.lookup/lead.follow_up_email/email.send/notification.send
nodes call back into (see that module's _internal_callback_node,
_lead_lookup_node, _lead_follow_up_email_node, and
_lead_acknowledgement_email_node). Not public: every route depends on
verify_internal_automation_token, and every tenant_id/business_id (body
for POST, query params for the GET) is checked against a real Business
row (BusinessRepository.get scopes by tenant automatically) rather than
trusted as-is — "no confiar ciegamente en IDs arbitrarios". Every route
that reaches a specific Lead additionally scopes by business_id via
LeadRepository.get_for_business, not just tenant_id — same isolation
guarantee Studio's own GET /businesses/{id}/leads already relies on
(app.routers.businesses), reused here rather than reimplemented.

/internal/leads/{id}/acknowledgement-email is what email.send's
translated node now calls (see app.automation.n8n.translator) instead
of n8n's own native emailSend node opening a raw SMTP connection —
Railway's n8n can't reliably reach Gmail's SMTP over that path, while
this is a plain HTTPS call this backend then fans out through its own
NotificationSender (Resend in production).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.dependencies import get_optional_notification_sender, get_session, verify_internal_automation_token
from app.domain.business_config import BusinessConfig
from app.errors import AppError
from app.notifications.sender import NotificationSender
from app.notifications.service import (
    LeadAcknowledgementEmailError,
    LeadFollowUpEmailError,
    NotificationDeliveryError,
    deliver_internal_notification,
    deliver_lead_acknowledgement_email,
    deliver_lead_follow_up_email,
)
from app.repositories.business import BusinessRepository
from app.repositories.internal_notification import InternalNotificationRepository
from app.repositories.lead import LeadRepository
from app.schemas.internal_automation import (
    LeadAcknowledgementEmailRequest,
    LeadAcknowledgementEmailResponse,
    LeadFollowUpEmailRequest,
    LeadFollowUpEmailResponse,
    LeadIngestRequest,
    LeadResponse,
    NotificationIngestRequest,
    NotificationResponse,
)

router = APIRouter(
    prefix="/internal", tags=["internal-automation"], dependencies=[Depends(verify_internal_automation_token)]
)


def _require_known_business(session: Session, tenant_id: UUID, business_id: UUID) -> Business:
    business = BusinessRepository(session).get(tenant_id, business_id)
    if business is None:
        raise AppError(
            "Unknown tenant/business combination.",
            code="unknown_tenant_business",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return business


@router.post("/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
def ingest_lead(payload: LeadIngestRequest, session: Session = Depends(get_session)) -> Lead:
    """P2 continuation: idempotent when `payload.lead_id` names a real
    lead already owned by this tenant/business — returns it unchanged
    instead of inserting a duplicate. This is what makes n8n's
    `lead.store` step (still calling this exact endpoint, unchanged) a
    safe no-op confirmation when the browser already posted to the new
    canonical POST /public/businesses/{id}/leads path and this backend
    already dispatched to n8n itself (app.automation.n8n.dispatch) —
    "no double POST" holds because the second call is a lookup, not an
    insert. `lead_id` naming a lead that doesn't resolve (wrong tenant,
    already deleted, or simply absent — every pre-existing caller) falls
    through to the original "always insert" behavior unchanged.
    """
    _require_known_business(session, payload.tenant_id, payload.business_id)
    repo = LeadRepository(session)

    if payload.lead_id is not None:
        existing = repo.get_for_business(payload.tenant_id, payload.business_id, payload.lead_id)
        if existing is not None:
            return existing

    lead = Lead(
        tenant_id=payload.tenant_id,
        business_id=payload.business_id,
        source=payload.source,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        message=payload.message,
    )
    return repo.add(lead)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: UUID, tenant_id: UUID, business_id: UUID, session: Session = Depends(get_session)) -> Lead:
    """The one real read this codebase does *after* a wait — see
    app.domain.workflow_config.generator's LOOKUP_LEAD_NODE_ID and
    app.automation.n8n.translator's _lead_lookup_node. `tenant_id`/
    `business_id` are required query params (FastAPI 422s a request
    missing either), not derived from anywhere implicit.
    LeadRepository.get_for_business — the same method
    app.routers.businesses' tenant-scoped leads list already uses —
    requires both to match, so a caller can never read a lead outside
    the exact tenant/business it names, even for a real lead id that
    belongs to a different business entirely.
    """
    _require_known_business(session, tenant_id, business_id)
    lead = LeadRepository(session).get_for_business(tenant_id, business_id, lead_id)
    if lead is None:
        raise AppError("Lead not found.", code="lead_not_found", status_code=status.HTTP_404_NOT_FOUND)
    return lead


@router.post("/leads/{lead_id}/follow-up-email", response_model=LeadFollowUpEmailResponse)
def send_lead_follow_up_email(
    lead_id: UUID,
    payload: LeadFollowUpEmailRequest,
    session: Session = Depends(get_session),
    sender: NotificationSender | None = Depends(get_optional_notification_sender),
) -> LeadFollowUpEmailResponse:
    """The lead.follow_up_email action's real send. Deliberately does
    not trust the n8n payload for the recipient or the lead's status —
    both are re-derived here from the lead's own row (the same one
    GET /internal/leads/{id} would return right now), same
    "authoritative check, not a mirror" reasoning as
    deliver_lead_follow_up_email's own docstring. `sent: false` (200)
    covers every legitimate "nothing to send" state (see that
    function); a real provider failure raises LeadFollowUpEmailError,
    mapped straight onto the HTTP response so n8n's own execution
    records the failure — never a silent 200 that hides it.
    """
    business = _require_known_business(session, payload.tenant_id, payload.business_id)
    lead = LeadRepository(session).get_for_business(payload.tenant_id, payload.business_id, lead_id)
    if lead is None:
        raise AppError("Lead not found.", code="lead_not_found", status_code=status.HTTP_404_NOT_FOUND)

    business_config = BusinessConfig.model_validate(business.config) if business.config else None

    try:
        sent = deliver_lead_follow_up_email(
            lead=lead, business_name=business.name, business_config=business_config, sender=sender
        )
    except LeadFollowUpEmailError as exc:
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc

    return LeadFollowUpEmailResponse(sent=sent)


@router.post("/leads/{lead_id}/acknowledgement-email", response_model=LeadAcknowledgementEmailResponse)
def send_lead_acknowledgement_email(
    lead_id: UUID,
    payload: LeadAcknowledgementEmailRequest,
    session: Session = Depends(get_session),
    sender: NotificationSender | None = Depends(get_optional_notification_sender),
) -> LeadAcknowledgementEmailResponse:
    """The email.send action's real send, called directly downstream of
    lead.store (see app.domain.workflow_config.generator's
    ACKNOWLEDGE_CUSTOMER_NODE_ID) — replaces what used to be n8n's own
    native emailSend node holding a raw SMTP credential. Deliberately
    does not trust the n8n payload for the recipient — re-derived here
    from the lead's own row (the same one POST /internal/leads just
    returned), same "authoritative check, not a mirror" reasoning as
    send_lead_follow_up_email above. `sent: false` (200) covers every
    legitimate "nothing to send" state (see
    deliver_lead_acknowledgement_email); a real provider failure raises
    LeadAcknowledgementEmailError, mapped straight onto the HTTP
    response so n8n's own execution records the failure — never a
    silent 200 that hides it.
    """
    business = _require_known_business(session, payload.tenant_id, payload.business_id)
    lead = LeadRepository(session).get_for_business(payload.tenant_id, payload.business_id, lead_id)
    if lead is None:
        raise AppError("Lead not found.", code="lead_not_found", status_code=status.HTTP_404_NOT_FOUND)

    business_config = BusinessConfig.model_validate(business.config) if business.config else None

    try:
        sent = deliver_lead_acknowledgement_email(
            lead=lead, business_name=business.name, business_config=business_config, sender=sender
        )
    except LeadAcknowledgementEmailError as exc:
        # Same "commit the real outcome before the request fails" reasoning
        # as ingest_notification's own except block above —
        # lead.acknowledgement_status was just set to FAILED in-memory
        # (app.notifications.service) and would otherwise be silently
        # discarded by get_session's rollback-on-exception.
        session.commit()
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc

    return LeadAcknowledgementEmailResponse(sent=sent)


@router.post("/notifications", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
def ingest_notification(
    payload: NotificationIngestRequest,
    session: Session = Depends(get_session),
    sender: NotificationSender | None = Depends(get_optional_notification_sender),
) -> InternalNotification:
    business = _require_known_business(session, payload.tenant_id, payload.business_id)

    contact = payload.email or payload.phone or "sin datos de contacto"
    summary = f"Nuevo lead ({payload.source}) de {payload.name or 'desconocido'} — {contact}"

    # delivered starts False and is only ever flipped to True by a real,
    # successful send below (see app.notifications.service). Committed
    # here, before any delivery attempt, so a failed or skipped send can
    # never lose the fact that this notification was due — see this
    # function's own except block below for why that matters.
    notification = InternalNotification(
        tenant_id=payload.tenant_id,
        business_id=payload.business_id,
        lead_id=payload.id,
        channel="internal",
        source=payload.source,
        summary=summary,
        delivered=False,
    )
    InternalNotificationRepository(session).add(notification)
    session.commit()

    business_config = BusinessConfig.model_validate(business.config) if business.config else None

    try:
        deliver_internal_notification(
            notification=notification, business_name=business.name, business_config=business_config, sender=sender
        )
    except NotificationDeliveryError as exc:
        # The notification row above is already committed, so this
        # request failing (get_session's own rollback-on-exception,
        # app.dependencies) can't lose it — only `delivered` stays
        # False, exactly reflecting reality. `status` was just flipped
        # to FAILED in-memory (app.notifications.service) though, and
        # that mutation is NOT yet committed — get_session's rollback
        # would silently discard it, leaving the row stuck at PENDING
        # forever instead of recording the real outcome, so it's
        # committed explicitly here before the request fails.
        session.commit()
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc

    return notification
