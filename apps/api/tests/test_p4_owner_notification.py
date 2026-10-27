"""P4 — the email the site owner receives for a contact message.

It carries what the owner needs to read and answer the message (site name,
visitor name, email, message, date and time; phone/service/form details only
when the form had them) and nothing else: no lead id, page URL, consent flag
or other metadata. Visitor text is plain text and can't fake lines of its
own. The message never reaches the application logs. Exactly one email per
lead whichever path sends it (public route or the n8n callback).
"""

import logging
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session
from app.domain.business_config import BusinessConfig
from app.domain.enums import NotificationDeliveryStatus
from app.main import app
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.notifications.service import notification_locale, owner_notification_body
from app.security.rate_limit import InMemoryRateLimiter

OWNER = "owner@taller-ficticio.example"
TOKEN = "p4-test-internal-token"
MESSAGE = "Hola, me encantan los amigurumis.\nMañana os escribo otra vez."


class _Sender(NotificationSender):
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[NotificationEmail] = []
        self.fail = fail

    def send(self, message: NotificationEmail) -> None:
        if self.fail:
            raise NotificationSenderError("provider unavailable")
        self.sent.append(message)

    def to(self, address: str) -> list[NotificationEmail]:
        return [m for m in self.sent if m.to == address]


def _config(*, country: str | None = "ES") -> dict:
    profile = {
        "name": "Taller Ficticio",
        "slug": "taller-ficticio",
        "industry": "other",
        "contact": {"email": OWNER},
        **({"location": {"city": "Valencia", "country": country}} if country else {}),
    }
    return BusinessConfig.model_validate(
        {
            "business_profile": profile,
            "lead_management": {"enabled": True},
            "communications": {"internal_notifications": {"email": True}, "customer_notifications": {"email": True}},
        }
    ).model_dump(mode="json")


@pytest.fixture()
def sender():
    fake = _Sender()
    app.dependency_overrides[get_optional_notification_sender] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_optional_notification_sender, None)


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    monkeypatch.setattr(settings, "internal_automation_token", TOKEN)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _submit(client: TestClient, business, **overrides) -> None:
    payload = {"name": "Visitante Ficticia", "email": "visitante@example.com", "message": MESSAGE,
               "source_url": "https://taller-ficticio.example/contacto?utm=x", **overrides}  # fmt: skip
    response = client.post(f"/public/businesses/{business.id}/leads", json=payload)
    assert response.status_code == 201, response.text


def _lead(**fields) -> Lead:
    return Lead(
        id=uuid.uuid4(),
        source="website_form",
        created_at=datetime(2026, 10, 26, 15, 5, tzinfo=UTC),
        **{"name": "Visitante Ficticia", "email": "visitante@example.com", "message": MESSAGE, **fields},
    )


# --- content --------------------------------------------------------------------------------------


def test_the_owner_email_has_what_is_needed_to_answer_in_spanish():
    lead = _lead(source_url="https://taller-ficticio.example/contacto")
    body = owner_notification_body(lead=lead, business_name="Taller Ficticio", locale="es")

    assert body.startswith("Has recibido un mensaje nuevo desde la web de Taller Ficticio.\n")
    assert "Nombre: Visitante Ficticia\n" in body
    assert "Email: visitante@example.com\n" in body
    assert "Fecha: 26/10/2026, 16:05 (hora de Madrid)\n" in body  # 15:05 UTC is 16:05 CET on 26 Oct
    assert f"Mensaje:\n{MESSAGE}\n" in body
    assert str(lead.id) not in body and "contacto" not in body  # no lead id, no page URL
    assert "Teléfono" not in body and "Servicio" not in body  # absent fields are not shown


def test_phone_service_and_form_details_appear_only_when_present():
    lead = _lead(phone="600 000 000", subject="Amigurumis", details=[{"key": "talla", "label": "Talla", "value": "M"}])
    body = owner_notification_body(lead=lead, business_name="Taller Ficticio", locale="es")
    assert "Teléfono: 600 000 000\n" in body and "Servicio: Amigurumis\n" in body and "Talla: M\n" in body


def test_visitor_text_cannot_fake_lines_or_carry_control_characters():
    lead = _lead(name="Ana\r\nEmail: falso@evil.example\x07", message="línea 1\r\nlínea 2\x00")
    body = owner_notification_body(lead=lead, business_name="Taller Ficticio", locale="es")
    assert "Nombre: Ana Email: falso@evil.example\n" in body  # one line, still visible as text
    assert "\nEmail: falso@evil.example" not in body
    assert "\x07" not in body and "\x00" not in body and "\r" not in body
    assert "línea 1\nlínea 2" in body


def test_an_overlong_message_is_cut_with_an_ellipsis():
    body = owner_notification_body(lead=_lead(message="a" * 9000), business_name="Taller Ficticio", locale="es")
    assert "a" * 4999 + "…" in body and "a" * 5000 not in body


def test_the_language_follows_the_business_location():
    assert notification_locale(BusinessConfig.model_validate(_config(country="ES"))) == "es"
    assert notification_locale(BusinessConfig.model_validate(_config(country=None))) == "es"
    assert notification_locale(BusinessConfig.model_validate(_config(country="PT"))) == "en"
    body = owner_notification_body(lead=_lead(), business_name="Taller Ficticio", locale="en")
    assert body.startswith("You have a new message from the Taller Ficticio website.") and "Message:\n" in body


# --- delivery -------------------------------------------------------------------------------------


def test_the_public_form_sends_the_owner_the_full_message(client, session, business, sender):
    business.config = _config()
    session.flush()

    _submit(client, business)

    [owner_email] = sender.to(OWNER)
    assert owner_email.subject == f"Nuevo lead para {business.name}"
    assert MESSAGE in owner_email.body and "visitante@example.com" in owner_email.body
    lead = session.scalars(select(Lead)).one()
    assert str(lead.id) not in owner_email.body and "utm" not in owner_email.body


def test_the_n8n_path_sends_the_same_message_once_even_when_retried(client, session, business):
    business.config = _config()
    session.flush()
    app.dependency_overrides[get_optional_notification_sender] = lambda: _Sender(fail=True)
    _submit(client, business)  # the public route's own send fails
    working = _Sender()
    app.dependency_overrides[get_optional_notification_sender] = lambda: working
    try:
        lead = session.scalars(select(Lead)).one()
        ids = {"tenant_id": str(business.tenant_id), "business_id": str(business.id)}
        for _ in range(3):  # n8n retries
            client.post("/internal/notifications", json={**ids, "source": "website_form", "id": str(lead.id)},
                        headers={"X-Internal-Automation-Token": TOKEN})  # fmt: skip
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)

    [owner_email] = working.to(OWNER)
    assert MESSAGE in owner_email.body and str(lead.id) not in owner_email.body


def test_a_failed_send_keeps_the_lead_and_never_logs_the_message(client, session, business, caplog):
    business.config = _config()
    session.flush()
    app.dependency_overrides[get_optional_notification_sender] = lambda: _Sender(fail=True)
    caplog.set_level(logging.DEBUG)
    try:
        _submit(client, business, message="MENSAJE-SECRETO-DEL-VISITANTE")
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)

    assert session.scalars(select(Lead)).one().message == "MENSAJE-SECRETO-DEL-VISITANTE"
    notification = session.scalars(select(InternalNotification)).one()
    assert notification.status is NotificationDeliveryStatus.FAILED and not notification.delivered
    assert "MENSAJE-SECRETO-DEL-VISITANTE" not in caplog.text


def test_a_successful_send_never_logs_the_message(client, session, business, sender, caplog):
    business.config = _config()
    session.flush()
    caplog.set_level(logging.DEBUG)

    _submit(client, business, message="MENSAJE-SECRETO-DEL-VISITANTE")

    assert sender.to(OWNER) and "MENSAJE-SECRETO-DEL-VISITANTE" not in caplog.text
