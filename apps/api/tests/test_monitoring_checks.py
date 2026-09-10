"""app.monitoring.checks: HTTP/DNS/TLS/form checks in isolation, no real
network calls — httpx/socket/ssl are monkeypatched. Covers the SSRF
guard (private/loopback/metadata addresses rejected before any network
call is attempted) and that UNKNOWN is never reported for a real
failure."""

import socket
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.domain.enums import HealthStatus
from app.monitoring.checks import check_dns, check_form_presence, check_http, check_tls


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "<html></html>") -> None:
        self.status_code = status_code
        self.text = text


def test_check_http_healthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.monitoring.checks.httpx.get", lambda *a, **k: _FakeResponse(200, "<html><form></form></html>")
    )

    result = check_http("https://example.com")

    assert result.status is HealthStatus.HEALTHY
    assert result.status_code == 200
    assert result.latency_ms is not None
    assert result.error is None


def test_check_http_client_error_is_degraded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.httpx.get", lambda *a, **k: _FakeResponse(404))

    result = check_http("https://example.com")

    assert result.status is HealthStatus.DEGRADED
    assert result.status_code == 404


def test_check_http_server_error_is_down(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.httpx.get", lambda *a, **k: _FakeResponse(503))

    result = check_http("https://example.com")

    assert result.status is HealthStatus.DOWN


def test_check_http_timeout_is_down(monkeypatch: pytest.MonkeyPatch):
    def _raise(*args, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _raise)

    result = check_http("https://example.com")

    assert result.status is HealthStatus.DOWN
    assert result.error == "Request timed out."


def test_check_http_connection_error_is_down(monkeypatch: pytest.MonkeyPatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _raise)

    result = check_http("https://example.com")

    assert result.status is HealthStatus.DOWN


# --- SSRF protection: no network call ever attempted for these ----------


def test_check_http_rejects_loopback(monkeypatch: pytest.MonkeyPatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("must never make a real network call for a blocked URL")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fail_if_called)

    result = check_http("http://127.0.0.1/admin")

    assert result.status is HealthStatus.UNKNOWN
    assert result.status_code is None


def test_check_http_rejects_cloud_metadata_address(monkeypatch: pytest.MonkeyPatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("must never make a real network call for a blocked URL")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fail_if_called)

    result = check_http("http://169.254.169.254/latest/meta-data/")

    assert result.status is HealthStatus.UNKNOWN


def test_check_http_rejects_private_network_range(monkeypatch: pytest.MonkeyPatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("must never make a real network call for a blocked URL")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fail_if_called)

    result = check_http("http://10.0.0.5/")

    assert result.status is HealthStatus.UNKNOWN


def test_check_http_rejects_non_http_scheme():
    result = check_http("file:///etc/passwd")

    assert result.status is HealthStatus.UNKNOWN


def test_check_http_never_leaks_ssrf_validator_internals(monkeypatch: pytest.MonkeyPatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("must never make a real network call for a blocked URL")

    monkeypatch.setattr("app.monitoring.checks.httpx.get", _fail_if_called)

    result = check_http("http://127.0.0.1/")

    assert result.error == "URL is not checkable."


# --- DNS -------------------------------------------------------------


def test_check_dns_healthy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.socket.gethostbyname", lambda host: "93.184.216.34")

    result = check_dns("example.com")

    assert result.status is HealthStatus.HEALTHY


def test_check_dns_failure(monkeypatch: pytest.MonkeyPatch):
    def _raise(host):
        raise socket.gaierror("no such host")

    monkeypatch.setattr("app.monitoring.checks.socket.gethostbyname", _raise)

    result = check_dns("does-not-exist.example")

    assert result.status is HealthStatus.DOWN


# --- TLS -------------------------------------------------------------


class _FakeTlsSocket:
    def __init__(self, not_after: str | None) -> None:
        self._not_after = not_after

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getpeercert(self):
        return {"notAfter": self._not_after} if self._not_after else {}


class _FakeContext:
    def __init__(self, not_after: str | None) -> None:
        self._not_after = not_after

    def wrap_socket(self, sock, server_hostname):
        return _FakeTlsSocket(self._not_after)


class _FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _not_after(days_from_now: int) -> str:
    when = datetime.now(UTC) + timedelta(days=days_from_now)
    return when.strftime("%b %d %H:%M:%S %Y GMT")


def test_check_tls_healthy_when_far_from_expiry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.socket.create_connection", lambda *a, **k: _FakeSocket())
    monkeypatch.setattr("app.monitoring.checks.ssl.create_default_context", lambda: _FakeContext(_not_after(90)))

    result = check_tls("example.com")

    assert result.status is HealthStatus.HEALTHY
    assert result.days_remaining is not None and result.days_remaining >= 89


def test_check_tls_degraded_when_expiring_soon(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.socket.create_connection", lambda *a, **k: _FakeSocket())
    monkeypatch.setattr("app.monitoring.checks.ssl.create_default_context", lambda: _FakeContext(_not_after(5)))

    result = check_tls("example.com")

    assert result.status is HealthStatus.DEGRADED


def test_check_tls_down_when_expired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.monitoring.checks.socket.create_connection", lambda *a, **k: _FakeSocket())
    monkeypatch.setattr("app.monitoring.checks.ssl.create_default_context", lambda: _FakeContext(_not_after(-1)))

    result = check_tls("example.com")

    assert result.status is HealthStatus.DOWN


def test_check_tls_down_on_handshake_failure(monkeypatch: pytest.MonkeyPatch):
    def _raise(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr("app.monitoring.checks.socket.create_connection", _raise)

    result = check_tls("example.com")

    assert result.status is HealthStatus.DOWN


# --- form presence -----------------------------------------------------


def test_check_form_presence_found():
    assert check_form_presence("<html><body><form></form></body></html>").status is HealthStatus.HEALTHY


def test_check_form_presence_missing():
    assert check_form_presence("<html><body>no form here</body></html>").status is HealthStatus.DEGRADED


def test_check_form_presence_unknown_when_page_never_loaded():
    assert check_form_presence(None).status is HealthStatus.UNKNOWN
