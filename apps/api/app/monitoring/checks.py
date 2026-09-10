"""Low-level, provider-agnostic website-health checks (P1.4): HTTP, DNS,
TLS certificate, and a safe contact-form presence check. Every function
here is called only against a URL/hostname already resolved from a
business's own persisted Website.deploy_url or an ACTIVE
CustomDomain.domain (see app.monitoring.service) — never a caller-
supplied value — and `check_http` re-validates through
app.security.ssrf.validate_outbound_url before making any real network
call, the same SSRF guard the n8n http.request action already goes
through, so this module never becomes a second, independently-tested
SSRF surface. `check_dns`/`check_tls` take an already-validated hostname
straight from `check_http`'s own URL, not a second untrusted input.

Never raises for a real-world failure (a down site, an expired
certificate, a DNS failure) — every check function returns a result
object whose `status`/`error` fields *are* that outcome; only a
genuine programming error propagates as an exception.
"""

import socket
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.domain.enums import HealthStatus
from app.security.ssrf import SSRFValidationError, validate_outbound_url

DEFAULT_HTTP_TIMEOUT_SECONDS = 10.0
DEFAULT_TLS_TIMEOUT_SECONDS = 5.0
# Capped so a very large page never bloats memory just to look for one
# `<form` marker — see check_form_presence below.
_MAX_BODY_BYTES_FOR_FORM_CHECK = 512_000


@dataclass(frozen=True)
class HttpCheckResult:
    status: HealthStatus
    status_code: int | None
    latency_ms: float | None
    # Decoded HTML body, capped — used only by check_form_presence below,
    # never persisted onto WebsiteHealthCheck itself.
    body: str | None
    error: str | None


def check_http(url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> HttpCheckResult:
    try:
        validate_outbound_url(url)
    except SSRFValidationError:
        # Never echo the validator's own message (it can include a
        # resolved IP) back through an operator-facing field — the
        # caller only needs to know this URL can't be checked at all.
        return HttpCheckResult(
            status=HealthStatus.UNKNOWN, status_code=None, latency_ms=None, body=None, error="URL is not checkable."
        )

    started = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.TimeoutException:
        return HttpCheckResult(
            status=HealthStatus.DOWN, status_code=None, latency_ms=None, body=None, error="Request timed out."
        )
    except httpx.HTTPError:
        return HttpCheckResult(
            status=HealthStatus.DOWN, status_code=None, latency_ms=None, body=None, error="Could not reach the website."
        )
    latency_ms = (time.monotonic() - started) * 1000

    if response.status_code >= 500:
        status = HealthStatus.DOWN
        error: str | None = f"Server returned HTTP {response.status_code}."
    elif response.status_code >= 400:
        status = HealthStatus.DEGRADED
        error = f"Server returned HTTP {response.status_code}."
    else:
        status = HealthStatus.HEALTHY
        error = None

    body = response.text[:_MAX_BODY_BYTES_FOR_FORM_CHECK] if status is not HealthStatus.DOWN else None
    return HttpCheckResult(
        status=status, status_code=response.status_code, latency_ms=latency_ms, body=body, error=error
    )


@dataclass(frozen=True)
class DnsCheckResult:
    status: HealthStatus
    error: str | None


def check_dns(hostname: str) -> DnsCheckResult:
    try:
        socket.gethostbyname(hostname)
    except OSError:
        return DnsCheckResult(status=HealthStatus.DOWN, error="DNS resolution failed.")
    return DnsCheckResult(status=HealthStatus.HEALTHY, error=None)


@dataclass(frozen=True)
class TlsCheckResult:
    status: HealthStatus
    expires_at: datetime | None
    days_remaining: int | None
    error: str | None


def check_tls(hostname: str, *, timeout: float = DEFAULT_TLS_TIMEOUT_SECONDS) -> TlsCheckResult:
    """Opens a real TLS connection on port 443 and reads the served
    certificate's expiration — the same thing a browser checks, not a
    lookup in some third-party certificate-transparency log. A plain
    (non-HTTPS) site simply has no certificate to check: reported as
    UNKNOWN, not DOWN, since "no TLS" isn't the same failure as "TLS is
    broken"."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as tls_sock:
                cert = tls_sock.getpeercert()
    except (OSError, ssl.SSLError):
        return TlsCheckResult(
            status=HealthStatus.DOWN, expires_at=None, days_remaining=None, error="TLS handshake failed."
        )

    not_after = cert.get("notAfter") if cert else None
    if not isinstance(not_after, str) or not not_after:
        return TlsCheckResult(
            status=HealthStatus.UNKNOWN,
            expires_at=None,
            days_remaining=None,
            error="No certificate expiration reported.",
        )

    expires_at = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    days_remaining = (expires_at - datetime.now(UTC)).days

    if days_remaining < 0:
        status = HealthStatus.DOWN
        error: str | None = "TLS certificate has expired."
    elif days_remaining <= 14:
        status = HealthStatus.DEGRADED
        error = "TLS certificate expires soon."
    else:
        status = HealthStatus.HEALTHY
        error = None

    return TlsCheckResult(status=status, expires_at=expires_at, days_remaining=days_remaining, error=error)


def hostname_from_url(url: str) -> str | None:
    return urlsplit(url).hostname


@dataclass(frozen=True)
class FormCheckResult:
    status: HealthStatus
    error: str | None


def check_form_presence(html_body: str | None) -> FormCheckResult:
    """Safe, synthetic, non-destructive: looks for a real `<form` element
    in the page's own already-fetched HTML (see check_http's `body`) —
    never submits anything, never touches the public lead endpoint, never
    creates a fake Lead row (P1.4's "do NOT fill the customer's Lead
    table with fake monitoring leads"). `html_body=None` (the HTTP check
    itself failed, or the response wasn't captured) reports UNKNOWN, not
    DOWN — this check has no independent signal in that case, it's
    purely riding on the HTTP check's own result."""
    if html_body is None:
        return FormCheckResult(status=HealthStatus.UNKNOWN, error="Page did not load.")
    if "<form" in html_body.lower():
        return FormCheckResult(status=HealthStatus.HEALTHY, error=None)
    return FormCheckResult(status=HealthStatus.DEGRADED, error="No contact form detected on the page.")
