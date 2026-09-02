"""Regression test for the test-isolation guards in conftest.py:
_block_real_smtp_connections_for_the_whole_suite (blocks smtplib.SMTP
itself, session-wide) and _no_real_notification_sender_by_default
(makes get_optional_notification_sender() -> None the default on the
real FastAPI app during tests). Together they mean no test in this
suite can ever open a real SMTP connection, even when apps/api/.env
carries real credentials — this file proves that for the two ways a
real connection could otherwise happen: a hand-built
SmtpNotificationSender with real-looking credentials, and
get_optional_notification_sender() called directly as a plain function
(which bypasses the FastAPI dependency-injection override entirely,
since that override only intercepts calls routed through the app).

If a future change ever weakens or removes the smtplib.SMTP guard,
these are the tests that catch it — none of them touch apps/api/.env
itself, only the in-memory `settings` object for their own duration.
"""

import smtplib

import pytest

from app.config import settings
from app.dependencies import get_optional_notification_sender
from app.notifications.sender import NotificationEmail
from app.notifications.smtp import SmtpNotificationSender
from tests.conftest import RealSmtpConnectionBlocked


def test_smtplib_smtp_itself_is_blocked_for_the_whole_suite():
    with pytest.raises(RealSmtpConnectionBlocked):
        smtplib.SMTP("smtp.gmail.com", 587)


def test_a_hand_built_smtp_notification_sender_cannot_reach_the_real_network():
    # Real-looking host/credentials, not an obviously-fake test double —
    # mirrors exactly what get_optional_notification_sender would build
    # from a fully-configured .env, proving the guard protects that
    # case too, not just tests that already know to use a fake sender.
    sender = SmtpNotificationSender(
        host="smtp.gmail.com",
        port=587,
        from_address="ops@example.com",
        username="someone",
        password="not-a-real-secret",
    )
    message = NotificationEmail(to="lead@example.com", subject="hola", body="hola")

    with pytest.raises(RealSmtpConnectionBlocked):
        sender.send(message)


def test_get_optional_notification_sender_called_directly_still_cannot_reach_the_network(
    monkeypatch: pytest.MonkeyPatch,
):
    # Simulates a fully-configured .env deterministically (monkeypatching
    # the in-memory settings object only — apps/api/.env itself is never
    # touched) rather than depending on whatever real credentials happen
    # to be there right now, so this stays a reliable regression check
    # regardless of environment. Calling the function directly (not
    # through FastAPI's dependency-injection system) bypasses
    # app.dependency_overrides entirely — exactly the gap the smtplib
    # guard exists to cover on its own.
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from_address", "ops@example.com")
    monkeypatch.setattr(settings, "smtp_username", "someone")
    monkeypatch.setattr(settings, "smtp_password", "not-a-real-secret")

    sender = get_optional_notification_sender()
    assert sender is not None  # confirms this really would build a real sender outside tests

    with pytest.raises(RealSmtpConnectionBlocked):
        sender.send(NotificationEmail(to="lead@example.com", subject="hola", body="hola"))
