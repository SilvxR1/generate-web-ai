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

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session, get_website_publisher
from app.domain.business_config import (
    BusinessConfig,
    BusinessProfile,
    CommunicationConfig,
    ContactInfo,
    LeadManagementConfig,
    NotificationPreferences,
)
from app.domain.enums import BusinessVertical, LeadSource
from app.main import app
from app.monitoring.alerts import AlertSeverity, send_operator_alert
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.publishing.publisher import WebsiteArtifact
from app.repositories.lead import LeadRepository
from app.repositories.website_version import WebsiteVersionRepository
from app.security.rate_limit import InMemoryRateLimiter
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

    def _fake_post(url, *, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.monitoring.alerts.httpx.post", _fake_post)

    with caplog.at_level(logging.ERROR, logger="app.monitoring.alerts"):
        send_operator_alert(AlertSeverity.CRITICAL, operation="test_op", summary="original failure")  # must not raise

    assert any("delivery failed" in record.message for record in caplog.records)


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
