"""A6.1 — pilot operational alerting: the minimal webhook-based operator
alert transport (app.monitoring.alerts), operational logging at the
existing publish/rollback/lead-notification failure boundaries, and the
sanitized public /health response (see tests/test_health.py for that
part). This file proves the P0 scope actually implemented from the A6
audit.

app.publishing.build.build_site is monkeypatched to a fake, instant
build (same convention as test_website_publish_service.py) — these
tests are about the logging/alerting boundary, not build fidelity."""

import logging
import uuid
from collections.abc import Generator

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.workflow import Workflow
from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session, get_website_publisher
from app.domain.business_config import (
    BusinessConfig,
    BusinessProfile,
    CommunicationConfig,
    ContactInfo,
    LeadManagementConfig,
    NotificationPreferences,
)
from app.domain.enums import BusinessVertical, LeadSource, WorkflowStatus
from app.main import app
from app.monitoring.alerts import AlertSeverity, send_operator_alert
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.publishing.publisher import WebsiteArtifact
from app.repositories.lead import LeadRepository
from app.repositories.website_version import WebsiteVersionRepository
from app.security.rate_limit import InMemoryRateLimiter
from tests.test_asset_upload_api import _AlwaysFailingStorageProvider
from tests.test_asset_upload_api import _upload as _upload_asset
from tests.test_website_publish_service import FakePublisher

SITE_CONFIG = {
    "brand": {"name": "Reforma Casa Valencia", "tagline": "Reformas integrales"},
    "theme": {
        "colors": {
            "primary": "#111827",
            "secondary": "#6b7280",
            "accent": "#2563eb",
            "background": "#ffffff",
            "foreground": "#111827",
        },
        "fonts": {"sans": "Inter, sans-serif"},
        "radius": {"base": "0.5rem", "lg": "1rem"},
    },
    "seo": {"title": "Reforma Casa Valencia", "description": "Empresa de reformas en Valencia."},
    "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {"heading": "Tu reforma, sin sorpresas"}}]}],
}


def _notification_enabled_config() -> BusinessConfig:
    """The minimal BusinessConfig shape that makes both
    deliver_internal_notification and deliver_lead_acknowledgement_email
    actually attempt a send instead of short-circuiting to
    NOT_CONFIGURED — without this, a NotificationSender fake's failure
    would never actually be exercised (see app.routers.public's own
    business_config is None -> skip-entirely branch)."""
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Reformas Valencia",
            slug="reformas-valencia",
            industry=BusinessVertical.HOME_RENOVATION,
            contact=ContactInfo(email="ops@reformasvalencia.example"),
        ),
        communications=CommunicationConfig(
            internal_notifications=NotificationPreferences(email=True),
            customer_notifications=NotificationPreferences(email=True),
        ),
        lead_management=LeadManagementConfig(enabled=True, sources=[LeadSource.WEBSITE_FORM]),
    )


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    artifact = WebsiteArtifact(files={"index.html": b"<html>fake build</html>"})
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: artifact)


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
        app.dependency_overrides.pop(get_website_publisher, None)
        app.dependency_overrides.pop(get_optional_notification_sender, None)


@pytest.fixture()
def notification_enabled_business(session, tenant: Tenant) -> Business:
    b = Business(
        tenant_id=tenant.id,
        name="Reformas Valencia",
        slug="reformas-valencia-a6",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        config=_notification_enabled_config().model_dump(mode="json"),
    )
    session.add(b)
    session.flush()
    return b


# --- alert transport (app.monitoring.alerts) --------------------------------


def test_unconfigured_webhook_is_a_silent_no_op(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", None)
    calls: list = []
    monkeypatch.setattr("app.monitoring.alerts.httpx.post", lambda *a, **k: calls.append((a, k)))

    send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="should not send")

    assert calls == []


def test_configured_webhook_sends_a_sanitized_text_payload(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/secret-path")
    monkeypatch.setattr(settings, "alert_webhook_provider", "slack")
    captured: dict = {}

    def _fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    business_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    send_operator_alert(
        AlertSeverity.WARNING,
        operation="lead_acknowledgement_email",
        summary="Failed to deliver the lead acknowledgement email: simulated provider outage",
        business_id=business_id,
        tenant_id=tenant_id,
        lead_id=lead_id,
    )

    assert captured["url"] == "https://hooks.example.com/secret-path"
    # Only the one field a generic/Slack-shaped webhook receiver needs.
    assert set(captured["json"].keys()) == {"text"}
    text = captured["json"]["text"]
    assert "WARNING" in text
    assert "lead_acknowledgement_email" in text
    assert str(business_id) in text
    assert str(tenant_id) in text
    assert str(lead_id) in text
    assert captured["timeout"] == 5.0


def test_webhook_failure_is_logged_and_never_raises(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/some-secret-token")
    monkeypatch.setattr(settings, "alert_webhook_provider", "slack")

    def _fake_post(url, *, json, timeout):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    with caplog.at_level(logging.ERROR, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="original failure")  # must not raise

    assert any("delivery failed" in record.message for record in caplog.records)
    assert "hooks.example.com" not in caplog.text
    assert "some-secret-token" not in caplog.text


def test_webhook_timeout_is_logged_and_never_raises(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/x")
    monkeypatch.setattr(settings, "alert_webhook_provider", "slack")

    def _fake_post(url, *, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    with caplog.at_level(logging.ERROR, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="original failure")  # must not raise

    assert any("delivery failed" in record.message for record in caplog.records)


# --- A6.3: Discord provider support ------------------------------------------


def test_discord_provider_sends_a_content_payload(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://discord.com/api/webhooks/secret/token")
    monkeypatch.setattr(settings, "alert_webhook_provider", "discord")
    captured: dict = {}

    def _fake_post(url, *, json, timeout):
        captured["json"] = json
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    send_operator_alert(AlertSeverity.CRITICAL, operation="website_publish", summary="provider rejected the deploy")

    assert set(captured["json"].keys()) == {"content"}
    assert "website_publish" in captured["json"]["content"]


def test_slack_provider_sends_a_text_payload(monkeypatch: pytest.MonkeyPatch):
    """Explicit provider=slack counterpart to the Discord test above —
    see also test_configured_webhook_sends_a_sanitized_text_payload,
    which already covers the full field-by-field content of the {"text": ...}
    shape; this one focuses purely on the provider-selection branch."""
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.slack.com/services/x")
    monkeypatch.setattr(settings, "alert_webhook_provider", "slack")
    captured: dict = {}

    def _fake_post(url, *, json, timeout):
        captured["json"] = json
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    send_operator_alert(AlertSeverity.WARNING, operation="lead_acknowledgement_email", summary="failed")

    assert set(captured["json"].keys()) == {"text"}


def test_url_present_but_provider_missing_is_a_no_op(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/x")
    monkeypatch.setattr(settings, "alert_webhook_provider", None)
    calls: list = []
    monkeypatch.setattr("app.monitoring.alerts.httpx.post", lambda *a, **k: calls.append((a, k)))

    with caplog.at_level(logging.WARNING, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="should not send")

    assert calls == []
    assert any("ALERT_WEBHOOK_PROVIDER" in record.message for record in caplog.records)
    assert "hooks.example.com" not in caplog.text


def test_url_present_but_provider_unsupported_is_a_no_op(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/x")
    monkeypatch.setattr(settings, "alert_webhook_provider", "pagerduty")
    calls: list = []
    monkeypatch.setattr("app.monitoring.alerts.httpx.post", lambda *a, **k: calls.append((a, k)))

    send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="should not send")

    assert calls == []


def test_provider_value_is_never_guessed_from_the_url(monkeypatch: pytest.MonkeyPatch):
    """A discord.com URL with no ALERT_WEBHOOK_PROVIDER set must NOT be
    silently treated as provider=discord — the provider is always an
    explicit setting."""
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://discord.com/api/webhooks/secret/token")
    monkeypatch.setattr(settings, "alert_webhook_provider", None)
    calls: list = []
    monkeypatch.setattr("app.monitoring.alerts.httpx.post", lambda *a, **k: calls.append((a, k)))

    send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="should not send")

    assert calls == []


def test_discord_transport_failure_never_raises_and_redacts_the_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://discord.com/api/webhooks/12345/super-secret-token")
    monkeypatch.setattr(settings, "alert_webhook_provider", "discord")

    def _fake_post(url, *, json, timeout):
        return httpx.Response(404, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    with caplog.at_level(logging.ERROR, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="original failure")  # must not raise

    assert any("delivery failed" in record.message for record in caplog.records)
    assert "discord.com" not in caplog.text
    assert "super-secret-token" not in caplog.text


def test_discord_timeout_never_raises(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setattr(settings, "alert_webhook_provider", "discord")

    def _fake_post(url, *, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    with caplog.at_level(logging.ERROR, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="original failure")  # must not raise

    assert any("delivery failed" in record.message for record in caplog.records)


def test_message_is_safely_truncated_within_discords_content_limit(monkeypatch: pytest.MonkeyPatch):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://discord.com/api/webhooks/x/y")
    monkeypatch.setattr(settings, "alert_webhook_provider", "discord")
    captured: dict = {}

    def _fake_post(url, *, json, timeout):
        captured["json"] = json
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="x" * 5000)

    content = captured["json"]["content"]
    assert len(content) <= 2000
    assert content.endswith("(truncated)")


# --- publish / rollback alerts (app.routers.businesses) ---------------------


def _create_business(client: TestClient, tenant_id: uuid.UUID) -> dict:
    payload = {
        "name": "Reforma Casa Valencia",
        "slug": "reforma-casa-valencia-a6",
        "vertical": "home_renovation",
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": "draft",
    }
    response = client.post("/businesses", json=payload, headers={"X-Tenant-Id": str(tenant_id)})
    assert response.status_code == 201, response.text
    return response.json()


def test_publish_failure_logs_and_alerts(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.com/x")
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.businesses.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher(fail=True)

    business = _create_business(client, tenant.id)
    with caplog.at_level(logging.ERROR, logger="app.publishing.service"):
        response = client.post(
            f"/businesses/{business['id']}/website/publish",
            json=SITE_CONFIG,
            headers={"X-Tenant-Id": str(tenant.id)},
        )

    assert response.status_code == 502
    assert any("Website publish failed" in record.message for record in caplog.records)
    assert len(alerts) == 1
    assert alerts[0]["severity"] is AlertSeverity.CRITICAL
    assert alerts[0]["operation"] == "website_publish"
    assert alerts[0]["business_id"] == uuid.UUID(business["id"])


def test_successful_publish_does_not_alert(client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch):
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.businesses.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher(fail=False)

    business = _create_business(client, tenant.id)
    response = client.post(
        f"/businesses/{business['id']}/website/publish", json=SITE_CONFIG, headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert response.status_code == 200
    assert alerts == []


def test_rollback_failure_from_a_failed_republish_logs_and_alerts(
    client: TestClient, tenant: Tenant, session, monkeypatch: pytest.MonkeyPatch
):
    """Rollback shares publish_website's own except block (A5.1's "rollback
    is just a republish"), so a rollback that fails because the provider
    itself rejects the republish must alert exactly like a direct publish
    failure — status_code 502, not the unrelated 404 case below."""
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.businesses.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    publisher = FakePublisher(fail=False)
    app.dependency_overrides[get_website_publisher] = lambda: publisher

    business = _create_business(client, tenant.id)
    publish_response = client.post(
        f"/businesses/{business['id']}/website/publish", json=SITE_CONFIG, headers={"X-Tenant-Id": str(tenant.id)}
    )
    assert publish_response.status_code == 200
    version_id = WebsiteVersionRepository(session).list_for_business(tenant.id, uuid.UUID(business["id"]))[0].id

    publisher.fail = True  # the rollback's own republish attempt now fails
    response = client.post(
        f"/businesses/{business['id']}/website/versions/{version_id}/rollback",
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 502
    assert len(alerts) == 1
    assert alerts[0]["severity"] is AlertSeverity.CRITICAL
    assert alerts[0]["operation"] == "website_rollback"


def test_rollback_to_an_unknown_version_does_not_alert(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    """A normal, user-caused 404 (bad version id) — explicitly excluded
    from alerting by the A6.1 spec ("Do NOT alert on... normal
    validation errors... user-caused 4xx input errors")."""
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.businesses.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher(fail=False)

    business = _create_business(client, tenant.id)
    response = client.post(
        f"/businesses/{business['id']}/website/versions/{uuid.uuid4()}/rollback",
        headers={"X-Tenant-Id": str(tenant.id)},
    )

    assert response.status_code == 404
    assert alerts == []


# --- lead notification/acknowledgement alerts (app.routers.public) ----------


class _FailingSender(NotificationSender):
    def send(self, message: NotificationEmail) -> None:
        raise NotificationSenderError("simulated provider outage")


def test_internal_notification_failure_persists_the_lead_and_sends_a_warning_alert(
    client: TestClient, notification_enabled_business: Business, session, monkeypatch: pytest.MonkeyPatch
):
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.public.send_operator_alert", lambda severity, **kw: alerts.append({"severity": severity, **kw})
    )
    app.dependency_overrides[get_optional_notification_sender] = lambda: _FailingSender()

    response = client.post(
        f"/public/businesses/{notification_enabled_business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Necesito un presupuesto para mi cocina.",
            "consent": True,
        },
    )

    assert response.status_code == 201
    leads = LeadRepository(session).list_for_business(
        notification_enabled_business.tenant_id, notification_enabled_business.id
    )
    assert len(leads) == 1
    warning_alerts = [a for a in alerts if a["operation"] == "internal_notification"]
    assert len(warning_alerts) == 1
    assert warning_alerts[0]["severity"] is AlertSeverity.WARNING
    assert warning_alerts[0]["lead_id"] == leads[0].id


def test_acknowledgement_email_failure_persists_the_lead_and_sends_a_warning_alert(
    client: TestClient, notification_enabled_business: Business, session, monkeypatch: pytest.MonkeyPatch
):
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.public.send_operator_alert", lambda severity, **kw: alerts.append({"severity": severity, **kw})
    )
    app.dependency_overrides[get_optional_notification_sender] = lambda: _FailingSender()

    response = client.post(
        f"/public/businesses/{notification_enabled_business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Necesito un presupuesto para mi cocina.",
            "consent": True,
        },
    )

    assert response.status_code == 201
    ack_alerts = [a for a in alerts if a["operation"] == "lead_acknowledgement_email"]
    assert len(ack_alerts) == 1
    assert ack_alerts[0]["severity"] is AlertSeverity.WARNING


def test_alert_transport_failure_never_affects_lead_persistence_or_response(
    client: TestClient, notification_enabled_business: Business, session, monkeypatch: pytest.MonkeyPatch
):
    """The alert webhook itself failing must never change the public
    lead endpoint's own response or lose the lead — A6.1's explicit
    "NEVER make the customer operation fail solely because alerting
    failed" requirement, exercised end-to-end through the real
    send_operator_alert (not a mock), against a real, unconfigured/
    unreachable webhook."""
    from app.config import settings

    monkeypatch.setattr(settings, "alert_webhook_url", "https://hooks.example.invalid/unreachable")
    monkeypatch.setattr(settings, "alert_webhook_provider", "slack")
    app.dependency_overrides[get_optional_notification_sender] = lambda: _FailingSender()

    response = client.post(
        f"/public/businesses/{notification_enabled_business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Necesito un presupuesto para mi cocina.",
            "consent": True,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"received": True}
    leads = LeadRepository(session).list_for_business(
        notification_enabled_business.tenant_id, notification_enabled_business.id
    )
    assert len(leads) == 1


# --- lead-alert sanitization: a hostile/sensitive-looking provider message --
# (e.g. what a real ResendApiError can carry — response.text is not
# guaranteed never to echo back submitted content) must never reach the
# external webhook payload, only the fixed generic summary.


class _SentinelFailingSender(NotificationSender):
    def send(self, message: NotificationEmail) -> None:
        raise NotificationSenderError("provider rejected request for private@example.test SECRET_SENTINEL")


def test_internal_notification_alert_never_contains_the_raw_provider_message(
    client: TestClient, notification_enabled_business: Business, monkeypatch: pytest.MonkeyPatch
):
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.public.send_operator_alert", lambda severity, **kw: alerts.append({"severity": severity, **kw})
    )
    app.dependency_overrides[get_optional_notification_sender] = lambda: _SentinelFailingSender()

    response = client.post(
        f"/public/businesses/{notification_enabled_business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Necesito un presupuesto para mi cocina.",
            "consent": True,
        },
    )

    assert response.status_code == 201
    matching = [a for a in alerts if a["operation"] == "internal_notification"]
    assert len(matching) == 1
    summary = matching[0]["summary"]
    assert "private@example.test" not in summary
    assert "SECRET_SENTINEL" not in summary
    assert summary == "Internal lead notification delivery failed."


def test_acknowledgement_email_alert_never_contains_the_raw_provider_message(
    client: TestClient, notification_enabled_business: Business, monkeypatch: pytest.MonkeyPatch
):
    alerts: list = []
    monkeypatch.setattr(
        "app.routers.public.send_operator_alert", lambda severity, **kw: alerts.append({"severity": severity, **kw})
    )
    app.dependency_overrides[get_optional_notification_sender] = lambda: _SentinelFailingSender()

    response = client.post(
        f"/public/businesses/{notification_enabled_business.id}/leads",
        json={
            "name": "Maria Garcia",
            "email": "maria@example.com",
            "message": "Necesito un presupuesto para mi cocina.",
            "consent": True,
        },
    )

    assert response.status_code == 201
    matching = [a for a in alerts if a["operation"] == "lead_acknowledgement_email"]
    assert len(matching) == 1
    summary = matching[0]["summary"]
    assert "private@example.test" not in summary
    assert "SECRET_SENTINEL" not in summary
    assert summary == "Lead acknowledgement email delivery failed."


# --- DB commit-failure alert (app.dependencies.get_session) -----------------
#
# Driven directly against the real get_session generator rather than
# through a full HTTP request: every other test in this file overrides
# get_session with a plain `yield session` (no commit at all — see this
# file's own `client` fixture), which is the correct isolation for
# everything else here but means the real function, and therefore this
# exact code path, is never exercised through the TestClient. No
# transaction semantics are altered to make this test possible — this
# calls the unmodified app.dependencies.get_session directly.


class _FailingCommitSession:
    """A Session whose commit() fails after the caller (the route body,
    simulated here by simply resuming the generator) already succeeded —
    the exact ambiguity window A6.1 targets: session.commit() happens in
    get_session, not inside publish_website, which only ever flushes."""

    def commit(self) -> None:
        raise RuntimeError("server closed the connection unexpectedly")

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_db_commit_failure_logs_and_alerts_generically(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    alerts: list = []
    monkeypatch.setattr(
        "app.dependencies.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    monkeypatch.setattr("app.dependencies._session_factory", lambda: _FailingCommitSession())

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/businesses/00000000-0000-0000-0000-000000000000/leads/x/notes",
            "headers": [],
            "query_string": b"",
        }
    )
    generator = get_session(request)

    with caplog.at_level(logging.CRITICAL, logger="app.dependencies"):
        session = next(generator)
        assert session is not None
        # Resuming past `yield` with no exception sent is exactly what
        # happens when a route body returns normally — this is what
        # drives get_session into its `else:` branch, where commit()
        # itself now raises.
        with pytest.raises(RuntimeError):
            next(generator)

    assert any("Database commit failed" in record.message for record in caplog.records)
    assert len(alerts) == 1
    assert alerts[0]["severity"] is AlertSeverity.CRITICAL
    assert alerts[0]["operation"] == "db_commit_after_success"
    summary = alerts[0]["summary"].lower()
    assert "cloudflare" not in summary
    assert "deployment" not in summary


class _SpySession:
    def __init__(self) -> None:
        self.commit_called = False
        self.rollback_called = False

    def commit(self) -> None:
        self.commit_called = True

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        pass


def test_get_session_never_commits_when_the_route_body_itself_raises(monkeypatch: pytest.MonkeyPatch):
    """The exact control-flow proof behind "no duplicate alert": when the
    route body raises (e.g. a publish failure the router already
    alerted about via its own except block), get_session's `except:`
    branch runs — never the `else:` branch that would call commit() and
    fire the generic db_commit_after_success alert a second time for
    the same underlying failure."""
    alerts: list = []
    monkeypatch.setattr(
        "app.dependencies.send_operator_alert",
        lambda severity, **kw: alerts.append({"severity": severity, **kw}),
    )
    spy_session = _SpySession()
    monkeypatch.setattr("app.dependencies._session_factory", lambda: spy_session)

    request = Request(
        {"type": "http", "method": "POST", "path": "/businesses/x/website/publish", "headers": [], "query_string": b""}
    )
    generator: Generator[Session, None, None] = get_session(request)  # type: ignore[assignment]
    session = next(generator)
    assert session is spy_session

    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("simulated route-body failure, already alerted by the router itself"))

    assert spy_session.commit_called is False
    assert spy_session.rollback_called is True
    assert alerts == []


def test_publish_failure_alerts_exactly_once_not_also_via_the_generic_commit_path(
    client: TestClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end companion to the get_session-level proof above: a real
    publish failure through the HTTP boundary produces exactly one
    alert (the router's own website_publish CRITICAL), and the generic
    db_commit_after_success path is never reached for it — this file's
    `client` fixture overrides get_session to a plain `yield session`
    (see its own definition), so app.dependencies.send_operator_alert
    can only ever be called if something outside that override reaches
    it, which a route-body failure never does."""
    router_alerts: list = []
    dependency_alerts: list = []
    monkeypatch.setattr(
        "app.routers.businesses.send_operator_alert",
        lambda severity, **kw: router_alerts.append({"severity": severity, **kw}),
    )
    monkeypatch.setattr(
        "app.dependencies.send_operator_alert",
        lambda severity, **kw: dependency_alerts.append({"severity": severity, **kw}),
    )
    app.dependency_overrides[get_website_publisher] = lambda: FakePublisher(fail=True)

    business = _create_business(client, tenant.id)
    response = client.post(
        f"/businesses/{business['id']}/website/publish", json=SITE_CONFIG, headers={"X-Tenant-Id": str(tenant.id)}
    )

    assert response.status_code == 502
    assert len(router_alerts) == 1
    assert router_alerts[0]["operation"] == "website_publish"
    assert dependency_alerts == []


# --- optional: n8n / R2 logging (no alert expected for either) -------------


def test_n8n_dispatch_failure_is_logged(
    client: TestClient,
    business: Business,
    session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr("app.routers.public.settings.n8n_base_url", "https://n8n.example.com")
    workflow = Workflow(
        tenant_id=business.tenant_id,
        business_id=business.id,
        name="Lead capture",
        status=WorkflowStatus.ACTIVE,
        local_workflow_id=f"{business.slug}-lead-capture",
        n8n_workflow_id="42",
    )
    session.add(workflow)
    session.flush()

    def _raise(**kwargs: object) -> None:
        from app.automation.n8n.dispatch import LeadDispatchError

        raise LeadDispatchError("n8n is down")

    monkeypatch.setattr("app.routers.public.dispatch_lead_to_workflow", _raise)

    with caplog.at_level(logging.ERROR, logger="app.routers.public"):
        response = client.post(
            f"/public/businesses/{business.id}/leads",
            json={
                "name": "Maria Garcia",
                "email": "maria@example.com",
                "message": "Necesito un presupuesto.",
                "consent": True,
            },
        )

    assert response.status_code == 201
    assert any("n8n dispatch failed" in record.message for record in caplog.records)


def test_r2_storage_failure_is_logged(
    client: TestClient, tenant: Tenant, business: Business, caplog: pytest.LogCaptureFixture
):
    from app.dependencies import get_storage_provider

    app.dependency_overrides[get_storage_provider] = lambda: _AlwaysFailingStorageProvider()
    try:
        with caplog.at_level(logging.ERROR, logger="app.routers.creative"):
            response = _upload_asset(client, business.id, tenant.id)
    finally:
        app.dependency_overrides.pop(get_storage_provider, None)

    assert response.status_code == 502
    assert any("Asset storage save failed" in record.message for record in caplog.records)
