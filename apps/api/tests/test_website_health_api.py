"""GET/POST /businesses/{id}/website-health[/check] (app.routers.website_health,
P1.4-P1.5): null before any check, cross-tenant 404, UNKNOWN when nothing
is published yet, overall status correctly rolling up from mocked
sub-checks (never reporting UNKNOWN as healthy), and rate limiting on the
real-network "check now" action."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.dependencies import get_rate_limiter, get_session
from app.domain.enums import DeployTarget, HealthStatus, WebsiteStatus
from app.main import app
from app.monitoring.checks import DnsCheckResult, FormCheckResult, HttpCheckResult, TlsCheckResult
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    # A single shared limiter instance across every request in the test —
    # the lambda must not construct a fresh (and therefore always-empty)
    # limiter per call, or the count could never accumulate (see
    # tests/test_rate_limit.py's own client fixture for the same shape).
    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _mock_checks(monkeypatch: pytest.MonkeyPatch, *, http: HealthStatus, dns: HealthStatus, tls: HealthStatus):
    monkeypatch.setattr(
        "app.monitoring.service.check_http",
        lambda url, timeout=10.0: HttpCheckResult(
            status=http,
            status_code=200 if http is HealthStatus.HEALTHY else 500,
            latency_ms=42.0,
            body="<form></form>",
            error=None,
        ),
    )
    monkeypatch.setattr("app.monitoring.service.check_dns", lambda hostname: DnsCheckResult(status=dns, error=None))
    monkeypatch.setattr(
        "app.monitoring.service.check_tls",
        lambda hostname: TlsCheckResult(status=tls, expires_at=None, days_remaining=90, error=None),
    )
    monkeypatch.setattr(
        "app.monitoring.service.check_form_presence",
        lambda body: FormCheckResult(status=HealthStatus.HEALTHY, error=None),
    )


def _publish_website(session, tenant: Tenant, business: Business) -> Website:
    website = Website(
        tenant_id=tenant.id,
        business_id=business.id,
        deploy_target=DeployTarget.CLOUDFLARE,
        deploy_url="https://example.pages.dev",
        status=WebsiteStatus.LIVE,
        deployed_at=datetime.now(UTC),
    )
    session.add(website)
    session.flush()
    return website


def test_get_health_is_null_before_any_check(client: TestClient, tenant: Tenant, business: Business):
    response = client.get(f"/businesses/{business.id}/website-health", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    assert response.json() is None


def test_get_health_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    import uuid

    response = client.get(f"/businesses/{uuid.uuid4()}/website-health", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 404


def test_check_now_with_no_published_website_is_unknown_not_healthy(
    client: TestClient, tenant: Tenant, business: Business
):
    response = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "unknown"
    assert body["http_status"] == "unknown"
    assert body["error_summary"]


def test_check_now_all_healthy_rolls_up_to_healthy(
    client: TestClient, session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.HEALTHY, dns=HealthStatus.HEALTHY, tls=HealthStatus.HEALTHY)

    response = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "healthy"
    assert body["http_status"] == "healthy"
    assert body["dns_status"] == "healthy"
    assert body["tls_status"] == "healthy"
    assert body["deployment_status"] == "healthy"
    assert body["form_status"] == "healthy"
    assert body["error_summary"] is None
    assert body["checked_url"] == "https://example.pages.dev"


def test_check_now_one_down_check_makes_overall_down(
    client: TestClient, session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.DOWN, dns=HealthStatus.HEALTHY, tls=HealthStatus.HEALTHY)

    response = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.json()["overall_status"] == "down"


def test_check_now_unknown_check_never_reported_as_healthy(
    client: TestClient, session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.HEALTHY, dns=HealthStatus.HEALTHY, tls=HealthStatus.UNKNOWN)

    response = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})

    body = response.json()
    assert body["tls_status"] == "unknown"
    assert body["overall_status"] == "unknown"
    assert body["overall_status"] != "healthy"


def test_check_now_persists_and_get_returns_the_same_snapshot(
    client: TestClient, session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.HEALTHY, dns=HealthStatus.HEALTHY, tls=HealthStatus.HEALTHY)

    checked = client.post(
        f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)}
    ).json()
    fetched = client.get(f"/businesses/{business.id}/website-health", headers={"X-Tenant-Id": str(tenant.id)}).json()

    assert fetched["id"] == checked["id"]
    assert fetched["overall_status"] == "healthy"


def test_check_now_never_leaks_across_tenants(
    client: TestClient,
    session,
    tenant: Tenant,
    other_tenant: Tenant,
    business: Business,
    monkeypatch: pytest.MonkeyPatch,
):
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.HEALTHY, dns=HealthStatus.HEALTHY, tls=HealthStatus.HEALTHY)
    client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})

    response = client.get(f"/businesses/{business.id}/website-health", headers={"X-Tenant-Id": str(other_tenant.id)})

    assert response.status_code == 404


def test_check_now_is_rate_limited(
    client: TestClient, session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "website_health_rate_limit_per_minute", 1)
    _publish_website(session, tenant, business)
    _mock_checks(monkeypatch, http=HealthStatus.HEALTHY, dns=HealthStatus.HEALTHY, tls=HealthStatus.HEALTHY)

    first = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})
    assert first.status_code == 200

    second = client.post(f"/businesses/{business.id}/website-health/check", headers={"X-Tenant-Id": str(tenant.id)})
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
