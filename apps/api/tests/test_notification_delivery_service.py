"""deliver_internal_notification (app.notifications.service) against a
fake NotificationSender — no network, no real email. Covers the
successful-delivery path (delivered flips to True, the right recipient/
subject/body are sent) and every legitimate no-op ("nothing to deliver
to yet"): no sender configured, no business config, no contact email,
and the business having opted out of email notifications — plus the
one real failure path, where a configured sender's send() itself
raises."""

import pytest

from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.domain.business_config import BusinessConfig, BusinessProfile, ContactInfo
from app.domain.enums import NotificationDeliveryStatus
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.notifications.service import (
    LeadAcknowledgementEmailError,
    NotificationDeliveryError,
    deliver_internal_notification,
    deliver_lead_acknowledgement_email,
)


class _FakeNotificationSender(NotificationSender):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[NotificationEmail] = []

    def send(self, message: NotificationEmail) -> None:
        if self.fail:
            raise NotificationSenderError("simulated provider failure")
        self.sent.append(message)


def _notification(**overrides: object) -> InternalNotification:
    fields: dict[str, object] = {
        "channel": "internal",
        "source": "website_form",
        "summary": "Nuevo lead (website_form) de Juan Perez — juan@example.com",
        "delivered": False,
    }
    fields.update(overrides)
    return InternalNotification(**fields)


def _business_config(
    *, email: str | None = "business@example.com", email_notifications_enabled: bool = True
) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Reformas Valencia",
            slug="reformas-valencia",
            industry="home_renovation",
            contact=ContactInfo(email=email) if email else None,
        ),
        communications={"internal_notifications": {"email": email_notifications_enabled}},
    )


def test_successful_delivery_marks_delivered_and_sends_to_the_business_contact_email():
    notification = _notification()
    sender = _FakeNotificationSender()

    deliver_internal_notification(
        notification=notification,
        business_name="Reformas Valencia",
        business_config=_business_config(),
        sender=sender,
    )

    assert notification.delivered is True
    assert notification.status is NotificationDeliveryStatus.SENT
    assert len(sender.sent) == 1
    sent = sender.sent[0]
    assert sent.to == "business@example.com"
    assert "Reformas Valencia" in sent.subject
    assert sent.body == notification.summary


def test_no_sender_configured_is_a_no_op_not_an_error():
    notification = _notification()

    deliver_internal_notification(
        notification=notification, business_name="Reformas Valencia", business_config=_business_config(), sender=None
    )

    assert notification.delivered is False
    assert notification.status is NotificationDeliveryStatus.NOT_CONFIGURED


def test_no_business_config_is_a_no_op_not_an_error():
    notification = _notification()
    sender = _FakeNotificationSender()

    deliver_internal_notification(
        notification=notification, business_name="Reformas Valencia", business_config=None, sender=sender
    )

    assert notification.delivered is False
    assert notification.status is NotificationDeliveryStatus.NOT_CONFIGURED
    assert sender.sent == []


def test_business_without_contact_email_is_a_no_op_not_an_error():
    notification = _notification()
    sender = _FakeNotificationSender()

    deliver_internal_notification(
        notification=notification,
        business_name="Reformas Valencia",
        business_config=_business_config(email=None),
        sender=sender,
    )

    assert notification.delivered is False
    assert notification.status is NotificationDeliveryStatus.NOT_CONFIGURED
    assert sender.sent == []


def test_business_opted_out_of_email_notifications_is_a_no_op_not_an_error():
    notification = _notification()
    sender = _FakeNotificationSender()

    deliver_internal_notification(
        notification=notification,
        business_name="Reformas Valencia",
        business_config=_business_config(email_notifications_enabled=False),
        sender=sender,
    )

    assert notification.delivered is False
    assert notification.status is NotificationDeliveryStatus.NOT_CONFIGURED
    assert sender.sent == []


def test_provider_failure_raises_and_leaves_delivered_false():
    notification = _notification()
    sender = _FakeNotificationSender(fail=True)

    with pytest.raises(NotificationDeliveryError) as exc_info:
        deliver_internal_notification(
            notification=notification,
            business_name="Reformas Valencia",
            business_config=_business_config(),
            sender=sender,
        )

    assert exc_info.value.code == "notification_delivery_failed"
    assert exc_info.value.status_code == 502
    assert notification.delivered is False
    assert notification.status is NotificationDeliveryStatus.FAILED


def _lead(**overrides: object) -> Lead:
    fields: dict[str, object] = {"source": "website_form", "name": "Juan Perez", "email": "juan@example.com"}
    fields.update(overrides)
    return Lead(**fields)


def _business_config_with_customer_acknowledgement(*, enabled: bool = True) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Reformas Valencia", slug="reformas-valencia", industry="home_renovation"
        ),
        communications={"customer_notifications": {"email": enabled}},
    )


def test_acknowledgement_email_sent_marks_status_sent():
    lead = _lead()
    sender = _FakeNotificationSender()

    sent = deliver_lead_acknowledgement_email(
        lead=lead,
        business_name="Reformas Valencia",
        business_config=_business_config_with_customer_acknowledgement(),
        sender=sender,
    )

    assert sent is True
    assert lead.acknowledgement_status is NotificationDeliveryStatus.SENT
    assert len(sender.sent) == 1
    assert sender.sent[0].to == "juan@example.com"


def test_acknowledgement_email_no_sender_is_not_configured():
    lead = _lead()

    sent = deliver_lead_acknowledgement_email(
        lead=lead,
        business_name="Reformas Valencia",
        business_config=_business_config_with_customer_acknowledgement(),
        sender=None,
    )

    assert sent is False
    assert lead.acknowledgement_status is NotificationDeliveryStatus.NOT_CONFIGURED


def test_acknowledgement_email_opted_out_is_not_configured():
    lead = _lead()
    sender = _FakeNotificationSender()

    sent = deliver_lead_acknowledgement_email(
        lead=lead,
        business_name="Reformas Valencia",
        business_config=_business_config_with_customer_acknowledgement(enabled=False),
        sender=sender,
    )

    assert sent is False
    assert lead.acknowledgement_status is NotificationDeliveryStatus.NOT_CONFIGURED
    assert sender.sent == []


def test_acknowledgement_email_provider_failure_marks_status_failed():
    lead = _lead()
    sender = _FakeNotificationSender(fail=True)

    with pytest.raises(LeadAcknowledgementEmailError):
        deliver_lead_acknowledgement_email(
            lead=lead,
            business_name="Reformas Valencia",
            business_config=_business_config_with_customer_acknowledgement(),
            sender=sender,
        )

    assert lead.acknowledgement_status is NotificationDeliveryStatus.FAILED
