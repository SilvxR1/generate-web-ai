"""Orchestrates one Website Health check for one business (P1.4): resolves
which URL/hostname is even safe and meaningful to check from that
business's own persisted Website/CustomDomain rows (never a caller-
supplied URL — the SSRF boundary this whole module respects), runs the
HTTP/DNS/TLS/form checks (app.monitoring.checks), rolls their four
outcomes up into one overall HealthStatus, and upserts the single latest
WebsiteHealthCheck snapshot for that business.

Deliberately synchronous and unscheduled — see app.monitoring's own
docstring for why. app.routers.website_health is the only caller.
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.custom_domain import CustomDomain
from app.db.models.website import Website
from app.db.models.website_health import WebsiteHealthCheck
from app.domain.enums import DomainStatus, HealthStatus, WebsiteStatus
from app.monitoring.checks import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    check_dns,
    check_form_presence,
    check_http,
    check_tls,
    hostname_from_url,
)
from app.repositories.custom_domain import CustomDomainRepository
from app.repositories.website import WebsiteRepository
from app.repositories.website_health import WebsiteHealthCheckRepository

_HEALTH_PRIORITY = (HealthStatus.DOWN, HealthStatus.DEGRADED, HealthStatus.UNKNOWN, HealthStatus.HEALTHY)


def _rollup(statuses: list[HealthStatus]) -> HealthStatus:
    """The overall state is the worst of its parts — DOWN beats DEGRADED
    beats UNKNOWN beats HEALTHY, so a single failing sub-check (or even a
    single un-checkable one) is never masked by the others passing.
    UNKNOWN never rolls up to HEALTHY (P1.5's explicit requirement)."""
    for candidate in _HEALTH_PRIORITY:
        if candidate in statuses:
            return candidate
    return HealthStatus.HEALTHY


def _deployment_status(website: Website | None) -> HealthStatus:
    if website is None:
        return HealthStatus.UNKNOWN
    return {
        WebsiteStatus.LIVE: HealthStatus.HEALTHY,
        WebsiteStatus.BUILDING: HealthStatus.DEGRADED,
        WebsiteStatus.FAILED: HealthStatus.DOWN,
        WebsiteStatus.INACTIVE: HealthStatus.DOWN,
        WebsiteStatus.DRAFT: HealthStatus.UNKNOWN,
    }[website.status]


def _resolve_checked_url(website: Website | None, custom_domain: CustomDomain | None) -> str | None:
    """Prefers the business's own ACTIVE custom domain — that's what a
    real visitor actually types/clicks — falling back to the Cloudflare
    Pages default URL. Both are already-persisted rows tied to this
    exact business; never a value taken from the request."""
    if custom_domain is not None and custom_domain.status is DomainStatus.ACTIVE:
        return f"https://{custom_domain.domain}"
    if website is not None and website.deploy_url:
        return website.deploy_url
    return None


def _first(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def run_website_health_check(
    session: Session, *, tenant_id: UUID, business_id: UUID, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS
) -> WebsiteHealthCheck:
    website = WebsiteRepository(session).get_by_business(tenant_id, business_id)
    custom_domain = CustomDomainRepository(session).get_by_business(tenant_id, business_id)
    checked_url = _resolve_checked_url(website, custom_domain)
    now = datetime.now(UTC)
    deployment_status = _deployment_status(website)
    deployed_at = website.deployed_at if website is not None else None

    if checked_url is None:
        return WebsiteHealthCheckRepository(session).upsert(
            tenant_id,
            business_id,
            checked_at=now,
            checked_url=None,
            overall_status=HealthStatus.UNKNOWN,
            http_status=HealthStatus.UNKNOWN,
            http_status_code=None,
            http_latency_ms=None,
            dns_status=HealthStatus.UNKNOWN,
            tls_status=HealthStatus.UNKNOWN,
            tls_expires_at=None,
            tls_days_remaining=None,
            deployment_status=deployment_status,
            deployment_last_deployed_at=deployed_at,
            form_status=HealthStatus.UNKNOWN,
            error_summary="This website has no reachable URL yet — publish it first.",
        )

    http_result = check_http(checked_url, timeout=timeout)
    hostname = hostname_from_url(checked_url)
    is_https = urlsplit(checked_url).scheme == "https"

    dns_result = check_dns(hostname) if hostname else None
    tls_result = check_tls(hostname) if hostname and is_https else None
    form_result = check_form_presence(http_result.body)

    dns_status = dns_result.status if dns_result is not None else HealthStatus.UNKNOWN
    tls_status = tls_result.status if tls_result is not None else HealthStatus.UNKNOWN

    overall = _rollup([http_result.status, dns_status, tls_status, deployment_status, form_result.status])
    error_summary = None
    if overall is not HealthStatus.HEALTHY:
        error_summary = _first(
            http_result.error,
            dns_result.error if dns_result else None,
            tls_result.error if tls_result else None,
            form_result.error,
        )

    return WebsiteHealthCheckRepository(session).upsert(
        tenant_id,
        business_id,
        checked_at=now,
        checked_url=checked_url,
        overall_status=overall,
        http_status=http_result.status,
        http_status_code=http_result.status_code,
        http_latency_ms=http_result.latency_ms,
        dns_status=dns_status,
        tls_status=tls_status,
        tls_expires_at=tls_result.expires_at if tls_result else None,
        tls_days_remaining=tls_result.days_remaining if tls_result else None,
        deployment_status=deployment_status,
        deployment_last_deployed_at=deployed_at,
        form_status=form_result.status,
        error_summary=error_summary,
    )
