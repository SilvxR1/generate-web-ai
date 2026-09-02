"""Two delivery functions sharing one NotificationSender (configured
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

* deliver_lead_follow_up_email: a Lead's own row -> the lead's own
  email. Never represented as an InternalNotification (that model means
  "the business's team was told", a different concept) and nothing is
  persisted for it at all — see that function's own docstring.

Both never raise for a legitimate "nothing to deliver to (yet)" state
— only for a real, configured provider call that itself failed.
"""

from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadStatus
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender


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


def deliver_internal_notification(
    *,
    notification: InternalNotification,
    business_name: str,
    business_config: BusinessConfig | None,
    sender: NotificationSender | None,
) -> None:
    """No-op (delivered stays False, no error) when: no sender is
    configured yet, this business has no persisted config, it has no
    contact email, or it has opted out of email notifications
    (CommunicationConfig.internal_notifications.email) — every one of
    those is a legitimate "not set up for this yet" state, not a
    failure. Only a real send attempt against a configured sender can
    raise NotificationDeliveryError.
    """
    if sender is None or business_config is None:
        return
    if not business_config.communications.internal_notifications.email:
        return
    contact = business_config.business_profile.contact
    if contact is None or not contact.email:
        return

    try:
        sender.send(
            NotificationEmail(
                to=contact.email,
                subject=f"Nuevo lead para {business_name}",
                body=notification.summary,
            )
        )
    except NotificationSenderError as exc:
        raise NotificationDeliveryError(
            f"Failed to deliver the internal notification email: {exc}",
            code="notification_delivery_failed",
            status_code=502,
        ) from exc

    notification.delivered = True


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
    from it on purpose), the lead has no email, or the lead is no
    longer NEW (checked again here, independently of whatever n8n's own
    condition already established — this function is the authoritative
    check, not merely a mirror of it). Only a real send attempt against
    a configured sender can raise LeadFollowUpEmailError.

    Content is fixed and business-name-based only for this MVP — no
    per-business copy, no template engine, no AI-generated text yet.
    """
    if sender is None or business_config is None:
        return False
    if not business_config.communications.customer_notifications.email:
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
            )
        )
    except NotificationSenderError as exc:
        raise LeadFollowUpEmailError(
            f"Failed to deliver the lead follow-up email: {exc}",
            code="lead_follow_up_email_failed",
            status_code=502,
        ) from exc

    return True
