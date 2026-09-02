"""app.security.ssrf: scheme restriction, localhost/loopback/private/
link-local/metadata blocking, and that an ordinary public URL passes —
the "SSRF private URLs rejected" / "public URL accepted" test bullets.

Uses literal IP addresses wherever possible (no DNS lookup needed, so
these stay hermetic) and monkeypatches socket.gethostbyname for the one
hostname-resolution test, rather than depending on live DNS.
"""

import pytest

from app.security.ssrf import SSRFValidationError, validate_outbound_url


def test_public_ip_url_accepted():
    # 1.1.1.1 (Cloudflare's public resolver) — a literal IP, so this
    # needs no DNS lookup and stays fully offline/deterministic.
    validate_outbound_url("https://1.1.1.1/webhook")  # must not raise


def test_non_http_scheme_rejected():
    with pytest.raises(SSRFValidationError, match="scheme"):
        validate_outbound_url("ftp://1.1.1.1/x")


def test_file_scheme_rejected():
    with pytest.raises(SSRFValidationError, match="scheme"):
        validate_outbound_url("file:///etc/passwd")


def test_localhost_hostname_rejected():
    with pytest.raises(SSRFValidationError, match="blocked"):
        validate_outbound_url("http://localhost/x")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://127.0.0.1:8000/x",
        "http://[::1]/x",
    ],
)
def test_loopback_ip_rejected(url: str):
    with pytest.raises(SSRFValidationError, match="blocked"):
        validate_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/x",
        "http://172.16.0.1/x",
        "http://192.168.1.1/x",
    ],
)
def test_private_ip_rejected(url: str):
    with pytest.raises(SSRFValidationError, match="blocked"):
        validate_outbound_url(url)


def test_link_local_ip_rejected():
    with pytest.raises(SSRFValidationError, match="blocked"):
        validate_outbound_url("http://169.254.1.1/x")


def test_cloud_metadata_ip_rejected():
    with pytest.raises(SSRFValidationError, match="metadata"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_unresolvable_hostname_rejected():
    with pytest.raises(SSRFValidationError, match="could not resolve"):
        validate_outbound_url("https://this-domain-definitely-does-not-exist.invalid/x")


def test_hostname_resolving_to_private_ip_rejected(monkeypatch: pytest.MonkeyPatch):
    # Proves resolution actually happens — a hostname-string check alone
    # would miss this; only DNS resolution catches "looks public,
    # resolves private".
    monkeypatch.setattr("app.security.ssrf.socket.gethostbyname", lambda host: "10.0.0.5")

    with pytest.raises(SSRFValidationError, match="blocked"):
        validate_outbound_url("https://looks-public.example/x")


def test_hostname_resolving_to_public_ip_accepted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.security.ssrf.socket.gethostbyname", lambda host: "93.184.216.34")

    validate_outbound_url("https://really-public.example/x")  # must not raise
