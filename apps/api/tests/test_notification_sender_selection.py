"""get_optional_notification_sender's provider-selection logic:
ResendNotificationSender is preferred whenever RESEND_API_KEY/
RESEND_FROM_ADDRESS are both configured, SmtpNotificationSender remains
the local/dev fallback when only SMTP is configured, and neither being
configured means None — the same "not set up yet, not a failure"
contract app.notifications.service depends on (see
test_smtp_isolation.py for why get_optional_notification_sender is also
covered by the session-wide smtplib.SMTP network guard).

Only ever monkeypatches the in-memory `settings` object, never
apps/api/.env itself, and never calls .send() on the returned sender —
Resend's own send behavior is covered by test_notification_sender_resend.py.
"""

import pytest

from app.config import settings
from app.dependencies import get_optional_notification_sender
from app.notifications.resend import ResendNotificationSender
from app.notifications.smtp import SmtpNotificationSender


def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "resend_api_key", None)
    monkeypatch.setattr(settings, "resend_from_address", None)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "smtp_from_address", None)


def test_returns_none_when_nothing_is_configured(monkeypatch: pytest.MonkeyPatch):
    _reset(monkeypatch)

    assert get_optional_notification_sender() is None


def test_returns_none_when_resend_api_key_is_set_without_a_from_address(monkeypatch: pytest.MonkeyPatch):
    # Missing config, not a guess: a from_address is required to actually
    # build a sender, so a bare API key alone must not select Resend.
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")

    assert get_optional_notification_sender() is None


def test_selects_resend_when_only_resend_is_configured(monkeypatch: pytest.MonkeyPatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "resend_from_address", "ops@example.com")

    sender = get_optional_notification_sender()

    assert isinstance(sender, ResendNotificationSender)


def test_falls_back_to_smtp_when_only_smtp_is_configured(monkeypatch: pytest.MonkeyPatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_address", "ops@example.com")

    sender = get_optional_notification_sender()

    assert isinstance(sender, SmtpNotificationSender)


def test_prefers_resend_over_smtp_when_both_are_configured(monkeypatch: pytest.MonkeyPatch):
    _reset(monkeypatch)
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "resend_from_address", "ops@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_address", "ops@example.com")

    sender = get_optional_notification_sender()

    assert isinstance(sender, ResendNotificationSender)
