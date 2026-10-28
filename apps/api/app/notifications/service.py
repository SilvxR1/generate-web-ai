"""Three delivery functions sharing one NotificationSender (configured
once per request, injected already-built — see
app.dependencies.get_optional_notification_sender) but kept
deliberately separate, never conflated:

* deliver_internal_notification: InternalNotification (already
  persisted) -> the business's own contact address
  (BusinessConfig.business_profile.contact.email). Always called
  *after* the InternalNotification row has been committed (see
  app.routers.internal_automation.ingest_notification) — a delivery
  attempt that's skipped or that fails must never be the reason a due
  notification goes unrecorded. It only ever flips `delivered` to True;
  a skip or failure leaves it exactly as ingest_notification set it
  (False), never touches the Lead this notification is about.

* deliver_lead_acknowledgement_email / deliver_lead_follow_up_email: a
  Lead's own row -> the lead's own email. Never represented as an
  InternalNotification (that model means "the business's team was
  told", a different concept) and nothing is persisted for either —
  see each function's own docstring for how their gating differs.

All three never raise for a legitimate "nothing to deliver to (yet)"
state — only for a real, configured provider call that itself failed.

Reply-To: emails to a lead reply to the business's own contact email
(the From address is the platform's shared sending domain, whose inbox
nobody reads); the owner notification about a lead replies to that
lead. Either is dropped — never the email — when the address is missing
or fails safe_reply_to.
"""

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadStatus, NotificationDeliveryStatus
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender, safe_reply_to


class NotificationDeliveryError(Exception):
    """Raised only when a *configured* NotificationSender's send() call
    itself failed. app.routers.internal_automation maps `code`/
    `status_code` straight onto the HTTP response n8n's HTTP Request
    node sees, so its own execution reports failure — never a bare 500,
    and never a silent 201 that hides a real delivery failure."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MAX_LINE_CHARS = 320
_MAX_MESSAGE_CHARS = 5000
_OWNER_TIMEZONE = "Europe/Madrid"
_OWNER_LABELS = {
    "es": {
        "intro": "Has recibido un mensaje nuevo desde la web de {business}.",
        "name": "Nombre",
        "email": "Email",
        "phone": "Teléfono",
        "subject": "Servicio",
        "date": "Fecha",
        "message": "Mensaje",
        "none": "(sin mensaje)",
        "reply": "Para responder, escribe a la dirección de email indicada arriba.",
        "zone": "hora de Madrid",
    },
    "en": {
        "intro": "You have a new message from the {business} website.",
        "name": "Name",
        "email": "Email",
        "phone": "Phone",
        "subject": "Service",
        "date": "Date",
        "message": "Message",
        "none": "(no message)",
        "reply": "To reply, write to the email address above.",
        "zone": "Madrid time",
    },
}


def _one_line(value: object) -> str:
    """Visitor text as one plain line: control characters and line breaks
    become spaces (the email is plain text — nothing is ever rendered as
    HTML — but a value can't start a fake line of its own)."""
    text = " ".join(_CONTROL.sub(" ", str(value)).replace("\r", " ").replace("\n", " ").split())
    return text if len(text) <= _MAX_LINE_CHARS else text[: _MAX_LINE_CHARS - 1] + "…"


def _paragraphs(value: str) -> str:
    text = _CONTROL.sub(" ", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    return text if len(text) <= _MAX_MESSAGE_CHARS else text[: _MAX_MESSAGE_CHARS - 1] + "…"


def notification_locale(business_config: BusinessConfig) -> str:
    """Spanish unless the business is located outside Spain — every site the
    deterministic generator builds is Spanish (generateSiteConfig)."""
    location = business_config.business_profile.location
    return "en" if location is not None and location.country and location.country.upper() != "ES" else "es"


def _submitted_at(when: datetime | None, labels: dict[str, str]) -> str:
    moment = when or datetime.now(UTC)
    if moment.tzinfo is None:  # SQLite hands back naive UTC timestamps
        moment = moment.replace(tzinfo=UTC)
    try:
        local = moment.astimezone(ZoneInfo(_OWNER_TIMEZONE))
        return f"{local:%d/%m/%Y, %H:%M} ({labels['zone']})"
    except ZoneInfoNotFoundError:  # no tz database in the runtime: UTC, said so
        return f"{moment.astimezone(UTC):%d/%m/%Y, %H:%M} (UTC)"


def _business_reply_to(business_config: BusinessConfig) -> str | None:
    contact = business_config.business_profile.contact
    return safe_reply_to(contact.email) if contact is not None else None


def owner_notification_body(*, lead: Lead, business_name: str, locale: str) -> str:
    """P4: what the owner needs to read and answer a contact message —
    never the lead id, the page URL, consent flags or other metadata.
    `subject` and form details appear only when the visitor's form had them."""
    labels = _OWNER_LABELS.get(locale, _OWNER_LABELS["es"])
    lines = [labels["intro"].format(business=_one_line(business_name)), ""]
    for key, value in (("name", lead.name), ("email", lead.email), ("phone", lead.phone), ("subject", lead.subject)):
        if value and str(value).strip():
            lines.append(f"{labels[key]}: {_one_line(value)}")
    for detail in lead.details or []:
        if isinstance(detail, dict) and str(detail.get("value") or "").strip():
            lines.append(f"{_one_line(detail.get('label') or detail.get('key') or '')}: {_one_line(detail['value'])}")
    lines.append(f"{labels['date']}: {_submitted_at(lead.created_at, labels)}")
    message = _paragraphs(lead.message or "")
    lines += ["", f"{labels['message']}:", message or labels["none"], "", labels["reply"]]
    return "\n".join(lines) + "\n"


def deliver_internal_notification(
    *,
    notification: InternalNotification,
    business_name: str,
    business_config: BusinessConfig | None,
    sender: NotificationSender | None,
    lead: Lead | None = None,
) -> None:
    """No-op (delivered stays False, no error) when: no sender is
    configured yet, this business has no persisted config, it has no
    contact email, or it has opted out of email notifications
    (CommunicationConfig.internal_notifications.email) — every one of
    those is a legitimate "not set up for this yet" state, not a
    failure. Only a real send attempt against a configured sender can
    raise NotificationDeliveryError.

    P4: with the `lead` this notification is about, the body is the
    owner-readable message (owner_notification_body); without one it is
    the stored one-line summary, as before.
    """
    if sender is None or business_config is None:
        notification.status = NotificationDeliveryStatus.NOT_CONFIGURED
        return
    if not business_config.communications.internal_notifications.email:
        notification.status = NotificationDeliveryStatus.NOT_CONFIGURED
        return
    contact = business_config.business_profile.contact
    if contact is None or not contact.email:
        notification.status = NotificationDeliveryStatus.NOT_CONFIGURED
        return

    try:
        sender.send(
            NotificationEmail(
                to=contact.email,
                subject=f"Nuevo lead para {business_name}",
                body=(
                    owner_notification_body(
                        lead=lead, business_name=business_name, locale=notification_locale(business_config)
                    )
                    if lead is not None
                    else notification.summary
                ),
                reply_to=safe_reply_to(lead.email) if lead is not None else None,
            )
        )
    except NotificationSenderError as exc:
        notification.status = NotificationDeliveryStatus.FAILED
        raise NotificationDeliveryError(
            f"Failed to deliver the internal notification email: {exc}",
            code="notification_delivery_failed",
            status_code=502,
        ) from exc

    notification.delivered = True
    notification.status = NotificationDeliveryStatus.SENT


class LeadAcknowledgementEmailError(Exception):
    """Same shape and role as NotificationDeliveryError/LeadFollowUpEmailError
    above, kept as its own class for the same "textually separate
    concepts" reasoning: a lead not getting acknowledged is distinct
    from a lead not getting a follow-up, even though both are emails to
    the lead itself."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def deliver_lead_acknowledgement_email(
    *, lead: Lead, business_name: str, business_config: BusinessConfig | None, sender: NotificationSender | None
) -> bool:
    """A real email *to the lead itself*, sent right after it's stored —
    the customer-facing counterpart to deliver_internal_notification,
    replacing what used to be n8n's native emailSend node (a raw SMTP
    connection Railway's n8n can't reliably open to Gmail). Routed
    through this backend's own NotificationSender instead — Resend in
    production (app.dependencies.get_optional_notification_sender) —
    the same cloud-safe HTTPS path deliver_internal_notification and
    deliver_lead_follow_up_email already use, never a second SMTP
    configuration living only in n8n.

    Deliberately never represented as an InternalNotification (that
    model means "the business's own team was told", a different
    concept). No lead-status check, unlike deliver_lead_follow_up_email:
    this fires immediately off the just-stored lead, not after a wait
    where the status could plausibly have moved on — acknowledging "we
    got your message" stays correct regardless of what happens to the
    lead afterwards.

    Returns False (no error) for every legitimate "don't send" state:
    no sender configured yet, no persisted business config, the
    business hasn't opted into customer-facing email
    (CommunicationConfig.customer_notifications.email — the same flag
    deliver_lead_follow_up_email checks, since both are customer-facing
    sends), or the lead has no email. Only a real send attempt against a
    configured sender can raise LeadAcknowledgementEmailError.

    Subject/body are fixed and business-name-based only for this MVP —
    same "no template engine yet" scope as deliver_lead_follow_up_email,
    and deliberately the same copy the retired n8n emailSend node used
    to send.
    """
    if sender is None or business_config is None:
        lead.acknowledgement_status = NotificationDeliveryStatus.NOT_CONFIGURED
        return False
    if not business_config.communications.customer_notifications.email:
        lead.acknowledgement_status = NotificationDeliveryStatus.NOT_CONFIGURED
        return False
    if not lead.email:
        lead.acknowledgement_status = NotificationDeliveryStatus.NOT_CONFIGURED
        return False

    greeting = f"Hola {lead.name}," if lead.name else "Hola,"
    try:
        sender.send(
            NotificationEmail(
                to=lead.email,
                subject="Hemos recibido tu mensaje",
                body=(
                    f"{greeting}\n\n"
                    "Gracias por contactarnos. Hemos recibido tu mensaje y te responderemos en breve.\n\n"
                    "Un saludo."
                ),
                reply_to=_business_reply_to(business_config),
            )
        )
    except NotificationSenderError as exc:
        lead.acknowledgement_status = NotificationDeliveryStatus.FAILED
        raise LeadAcknowledgementEmailError(
            f"Failed to deliver the lead acknowledgement email: {exc}",
            code="lead_acknowledgement_email_failed",
            status_code=502,
        ) from exc

    lead.acknowledgement_status = NotificationDeliveryStatus.SENT
    return True


class LeadFollowUpEmailError(Exception):
    """Same shape and role as NotificationDeliveryError above, kept as
    its own class rather than reused — these two error types map onto
    two different concepts (a business's own team not getting notified,
    vs. a lead not getting emailed) that this module deliberately keeps
    textually separate, same as the two delivery functions themselves.
    """

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def deliver_lead_follow_up_email(
    *, lead: Lead, business_name: str, business_config: BusinessConfig | None, sender: NotificationSender | None
) -> bool:
    """A real email *to the lead itself* — deliberately never an
    InternalNotification row (that model means "the business's own team
    was told about something"; this is a different concept, the lead
    being contacted directly). Nothing is persisted here at all: n8n's
    own execution record is this action's audit trail (a failed send
    raises, which the caller — app.routers.internal_automation — turns
    into a failed HTTP response, so n8n's own log carries the failure;
    see that router's docstring).

    Returns False (no error) for every legitimate "don't send" state:
    no sender configured yet, no persisted business config, the
    business hasn't opted into customer-facing email
    (CommunicationConfig.customer_notifications.email — the customer-
    facing counterpart of internal_notifications.email, and distinct
    from it on purpose), the business has follow-up turned off
    (automation.follow_up.enabled — re-checked here because an n8n
    workflow generated while it was on keeps calling this endpoint
    after the business turns it off; the immediate acknowledgement
    shares customer_notifications.email and must keep working), the
    lead has no email, or the lead is no longer NEW (checked again
    here, independently of whatever n8n's own condition already
    established — this function is the authoritative check, not merely
    a mirror of it). Only a real send attempt against a configured
    sender can raise LeadFollowUpEmailError.

    Content is fixed and business-name-based only for this MVP — no
    per-business copy, no template engine, no AI-generated text yet.
    """
    if sender is None or business_config is None:
        return False
    if not business_config.communications.customer_notifications.email:
        return False
    if not business_config.automation.follow_up.enabled:
        return False
    if lead.status != LeadStatus.NEW:
        return False
    if not lead.email:
        return False

    greeting = f"Hola {lead.name}," if lead.name else "Hola,"
    try:
        sender.send(
            NotificationEmail(
                to=lead.email,
                subject=f"Seguimos disponibles para ayudarte — {business_name}",
                body=(
                    f"{greeting}\n\n"
                    f"Queriamos confirmar que en {business_name} seguimos disponibles para ayudarte con tu "
                    "consulta. Si tienes alguna pregunta, responde a este correo y te atenderemos con gusto.\n\n"
                    f"Un saludo,\nEl equipo de {business_name}"
                ),
                reply_to=_business_reply_to(business_config),
            )
        )
    except NotificationSenderError as exc:
        raise LeadFollowUpEmailError(
            f"Failed to deliver the lead follow-up email: {exc}",
            code="lead_follow_up_email_failed",
            status_code=502,
        ) from exc

    return True
