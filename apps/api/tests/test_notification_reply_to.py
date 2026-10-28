"""Reply-To on every outbound notification email: safe_reply_to's
validation (valid / missing / invalid / header-injection attempts), both
providers putting it on the wire only when present, and each of the
three delivery paths choosing the right address — the business contact
for emails to a lead, the lead for the owner notification — while a
missing or bad address only ever drops the Reply-To, never the email."""

import email
import smtplib

import httpx
import pytest

from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.domain.business_config import BusinessConfig, BusinessProfile, ContactInfo
from app.domain.enums import LeadStatus, NotificationDeliveryStatus
from app.notifications.resend import ResendNotificationSender
from app.notifications.sender import NotificationEmail, NotificationSender, safe_reply_to
from app.notifications.service import (
    deliver_internal_notification,
    deliver_lead_acknowledgement_email,
    deliver_lead_follow_up_email,
)
from app.notifications.smtp import SmtpNotificationSender

BUSINESS_EMAIL = "hola@cositas.example"
LEAD_EMAIL = "visitante@example.com"


class _FakeNotificationSender(NotificationSender):
    def __init__(self) -> None:
        self.sent: list[NotificationEmail] = []

    def send(self, message: NotificationEmail) -> None:
        self.sent.append(message)


def _business_config(*, email: str | None = BUSINESS_EMAIL, follow_up: bool = True) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas",
            slug="cositas",
            industry="home_renovation",
            contact=ContactInfo(email=email) if email else None,
        ),
        communications={"internal_notifications": {"email": True}, "customer_notifications": {"email": True}},
        automation={"follow_up": {"enabled": follow_up}},
    )


def _lead(**overrides: object) -> Lead:
    fields: dict[str, object] = {"name": "Ana", "email": LEAD_EMAIL, "status": LeadStatus.NEW, "source": "website_form"}
    fields.update(overrides)
    return Lead(**fields)


def _notification() -> InternalNotification:
    return InternalNotification(channel="internal", source="website_form", summary="Nuevo lead", delivered=False)


# --- safe_reply_to ------------------------------------------------------------


@pytest.mark.parametrize("value", ["hola@cositas.example", "a.b+tag@sub.example.es"])
def test_a_valid_address_is_kept(value):
    assert safe_reply_to(value) == value


@pytest.mark.parametrize("value", [None, "", 42])
def test_a_missing_address_gives_none(value):
    assert safe_reply_to(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "not-an-email",
        "@example.com",
        "a@b",
        "Ana <ana@example.com>",
        "ana@example.com, otro@example.com",
        "ana@example.com\r\nBcc: victim@example.com",
        "ana@example.com\nBcc: victim@example.com",
        "ana@example.com\x00",
        " ana@example.com",
    ],
)
def test_an_invalid_or_injecting_address_gives_none(value):
    assert safe_reply_to(value) is None


def test_the_email_model_itself_refuses_a_header_injecting_reply_to():
    with pytest.raises(ValueError):
        NotificationEmail(to="a@example.com", subject="s", body="b", reply_to="x@example.com\r\nBcc: v@example.com")


# --- providers ----------------------------------------------------------------


def _resend_payload(message: NotificationEmail) -> dict:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "email-1"})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.resend.com")
    ResendNotificationSender(api_key="re_test", from_address="from@example.com", http_client=client).send(message)
    return httpx.Response(200, content=requests[0].content).json()


def test_resend_sends_reply_to_when_present():
    payload = _resend_payload(NotificationEmail(to="a@example.com", subject="s", body="b", reply_to=BUSINESS_EMAIL))
    assert payload["reply_to"] == [BUSINESS_EMAIL]


def test_resend_omits_reply_to_when_absent():
    payload = _resend_payload(NotificationEmail(to="a@example.com", subject="s", body="b"))
    assert "reply_to" not in payload


class _FakeSmtp:
    sent: list[object] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_FakeSmtp":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def starttls(self) -> None:
        pass

    def send_message(self, message: object) -> None:
        _FakeSmtp.sent.append(message)


@pytest.mark.parametrize("reply_to", [BUSINESS_EMAIL, None])
def test_smtp_sets_the_reply_to_header_only_when_present(monkeypatch: pytest.MonkeyPatch, reply_to):
    _FakeSmtp.sent = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtp)
    sender = SmtpNotificationSender(host="smtp.example.com", port=587, from_address="from@example.com")
    sender.send(NotificationEmail(to="a@example.com", subject="s", body="b", reply_to=reply_to))
    parsed = email.message_from_string(str(_FakeSmtp.sent[0]))
    assert parsed["Reply-To"] == reply_to
    assert parsed["From"] == "from@example.com"


# --- delivery paths -----------------------------------------------------------


def test_the_acknowledgement_replies_to_the_business_contact_email():
    sender = _FakeNotificationSender()
    assert deliver_lead_acknowledgement_email(
        lead=_lead(), business_name="Cositas", business_config=_business_config(), sender=sender
    )
    assert sender.sent[0].to == LEAD_EMAIL
    assert sender.sent[0].reply_to == BUSINESS_EMAIL


def test_the_follow_up_replies_to_the_business_contact_email():
    sender = _FakeNotificationSender()
    assert deliver_lead_follow_up_email(
        lead=_lead(), business_name="Cositas", business_config=_business_config(), sender=sender
    )
    assert sender.sent[0].reply_to == BUSINESS_EMAIL


def test_the_follow_up_still_respects_follow_up_enabled():
    sender = _FakeNotificationSender()
    assert not deliver_lead_follow_up_email(
        lead=_lead(), business_name="Cositas", business_config=_business_config(follow_up=False), sender=sender
    )
    assert sender.sent == []


def test_emails_to_a_lead_still_go_out_without_reply_to_when_the_business_has_no_contact_email():
    sender = _FakeNotificationSender()
    config = _business_config(email=None)
    lead = _lead()
    assert deliver_lead_acknowledgement_email(lead=lead, business_name="Cositas", business_config=config, sender=sender)
    assert deliver_lead_follow_up_email(lead=lead, business_name="Cositas", business_config=config, sender=sender)
    assert [m.reply_to for m in sender.sent] == [None, None]
    assert lead.acknowledgement_status is NotificationDeliveryStatus.SENT


def test_the_owner_notification_replies_to_the_lead():
    sender = _FakeNotificationSender()
    notification = _notification()
    deliver_internal_notification(
        notification=notification,
        business_name="Cositas",
        business_config=_business_config(),
        sender=sender,
        lead=_lead(),
    )
    assert sender.sent[0].to == BUSINESS_EMAIL
    assert sender.sent[0].reply_to == LEAD_EMAIL
    assert notification.delivered is True


@pytest.mark.parametrize("lead_email", [None, "", "not-an-email", "ana@example.com\r\nBcc: victim@example.com"])
def test_the_owner_notification_is_still_sent_without_reply_to_for_a_missing_or_bad_lead_email(lead_email):
    sender = _FakeNotificationSender()
    notification = _notification()
    deliver_internal_notification(
        notification=notification,
        business_name="Cositas",
        business_config=_business_config(),
        sender=sender,
        lead=_lead(email=lead_email, phone="+34600000000"),
    )
    assert len(sender.sent) == 1
    assert sender.sent[0].reply_to is None
    assert notification.status is NotificationDeliveryStatus.SENT


def test_the_summary_only_owner_notification_has_no_reply_to():
    sender = _FakeNotificationSender()
    deliver_internal_notification(
        notification=_notification(), business_name="Cositas", business_config=_business_config(), sender=sender
    )
    assert sender.sent[0].reply_to is None
