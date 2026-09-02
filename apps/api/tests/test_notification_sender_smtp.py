"""SmtpNotificationSender against a fake smtplib.SMTP (monkeypatched —
no real network connection, no real email ever sent): a successful send
constructs the right MIME message and calls starttls/login/send_message
in order; a raised smtplib/OSError error becomes a NotificationSenderError
that never leaks the password."""

import smtplib

import pytest

from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail
from app.notifications.smtp import SmtpNotificationSender


class _FakeSmtpConnection:
    """Records what SmtpNotificationSender does with an SMTP connection,
    shaped like smtplib.SMTP's context-manager surface — never opens a
    real socket."""

    instances: list["_FakeSmtpConnection"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_calls: list[tuple[str, str]] = []
        self.sent_messages: list[object] = []
        _FakeSmtpConnection.instances.append(self)

    def __enter__(self) -> "_FakeSmtpConnection":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def send_message(self, message: object) -> None:
        self.sent_messages.append(message)


class _RaisingSmtpConnection(_FakeSmtpConnection):
    def send_message(self, message: object) -> None:
        raise smtplib.SMTPRecipientsRefused({"lead@example.com": (550, b"mailbox unavailable")})


@pytest.fixture(autouse=True)
def _reset_instances():
    _FakeSmtpConnection.instances = []
    yield
    _FakeSmtpConnection.instances = []


def _sender(**overrides: object) -> SmtpNotificationSender:
    kwargs: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "from_address": "notificaciones@generate-web-ai.example",
        "username": "smtp-user",
        "password": "super-secret-smtp-password",
    }
    kwargs.update(overrides)
    return SmtpNotificationSender(**kwargs)


def _message() -> NotificationEmail:
    return NotificationEmail(to="business@example.com", subject="Nuevo lead", body="Juan Perez — +34600000000")


def test_send_constructs_the_expected_mime_message(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtpConnection)

    _sender().send(_message())

    connection = _FakeSmtpConnection.instances[0]
    assert connection.host == "smtp.example.com"
    assert connection.port == 587
    assert connection.started_tls is True
    assert connection.login_calls == [("smtp-user", "super-secret-smtp-password")]
    sent = connection.sent_messages[0]
    assert sent["From"] == "notificaciones@generate-web-ai.example"
    assert sent["To"] == "business@example.com"
    assert sent["Subject"] == "Nuevo lead"
    assert sent.get_content().strip() == "Juan Perez — +34600000000"


def test_send_without_credentials_skips_login(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtpConnection)

    _sender(username=None, password=None).send(_message())

    connection = _FakeSmtpConnection.instances[0]
    assert connection.login_calls == []


def test_send_without_tls_skips_starttls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSmtpConnection)

    _sender(use_tls=False).send(_message())

    connection = _FakeSmtpConnection.instances[0]
    assert connection.started_tls is False


def test_provider_failure_becomes_a_notification_sender_error_without_leaking_the_password(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(smtplib, "SMTP", _RaisingSmtpConnection)

    with pytest.raises(NotificationSenderError) as exc_info:
        _sender().send(_message())

    assert "super-secret-smtp-password" not in str(exc_info.value)


def test_connection_error_becomes_a_notification_sender_error(monkeypatch: pytest.MonkeyPatch):
    def _raise_connection_refused(host: str, port: int, timeout: float) -> _FakeSmtpConnection:
        raise OSError("Connection refused")

    monkeypatch.setattr(smtplib, "SMTP", _raise_connection_refused)

    with pytest.raises(NotificationSenderError):
        _sender().send(_message())
