"""Outbound-URL SSRF validation for the `http.request` workflow action.

Deliberately NOT in app.domain.workflow_config: real validation needs a
DNS lookup to catch a hostname that *resolves* to a private/metadata
address (a hostname-string check alone is trivially bypassed by DNS) —
that's I/O, non-deterministic, and slow, none of which belongs in a
domain model's synchronous Pydantic validator. This module is called
from the n8n translator instead (app.automation.n8n.translator), which
is already the layer that turns a URL into an outbound network call.

Redirect validation is explicitly NOT done here yet — n8n's own HTTP
Request node executes the actual request and may follow redirects that
this pre-check can't see. See this module's LIMITATIONS note in the
execution-layer phase's final response.
"""

import ipaddress
import socket
from urllib.parse import urlsplit


class SSRFValidationError(ValueError):
    pass


_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}
# The AWS/GCP/Azure/DigitalOcean cloud metadata endpoint — the single
# most common real-world SSRF target.
_BLOCKED_IPS = {"169.254.169.254"}


def validate_outbound_url(url: str) -> None:
    """Raises SSRFValidationError for anything not safe to let an
    external system (n8n) fetch on our behalf. Silence (no return value)
    means the URL passed every check."""
    parts = urlsplit(url)

    if parts.scheme not in ("http", "https"):
        raise SSRFValidationError(f"URL scheme {parts.scheme!r} is not allowed; only http/https.")

    hostname = parts.hostname
    if not hostname:
        raise SSRFValidationError("URL has no hostname.")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFValidationError(f"URL host {hostname!r} is blocked.")

    resolved_ip = _resolve(hostname)

    if str(resolved_ip) in _BLOCKED_IPS:
        raise SSRFValidationError(f"URL resolves to a blocked cloud metadata address ({resolved_ip}).")

    if (
        resolved_ip.is_loopback
        or resolved_ip.is_private
        or resolved_ip.is_link_local
        or resolved_ip.is_reserved
        or resolved_ip.is_multicast
        or resolved_ip.is_unspecified
    ):
        raise SSRFValidationError(f"URL resolves to a blocked address range ({resolved_ip}).")


def _resolve(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    # A literal IP needs no DNS lookup at all; a hostname does, and that
    # lookup is exactly what catches "a public-looking domain that
    # actually points at 127.0.0.1".
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        pass

    try:
        return ipaddress.ip_address(socket.gethostbyname(hostname))
    except (OSError, ValueError) as exc:
        raise SSRFValidationError(f"could not resolve host {hostname!r}: {exc}") from exc
