"""C2.1 — the visitor's IP for per-visitor rate limiting, behind a proxy.

Railway's edge proxy connects to the API from private addresses
(100.64.0.0/10, observed in production request logs), so
`request.client.host` names the proxy, not the visitor: every visitor shares
a handful of buckets. `X-Forwarded-For` carries the real address but is
client-controlled, so it is only consulted when the direct peer is a proxy
the operator explicitly trusts (`settings.trusted_proxy_cidrs`, empty by
default = today's behaviour). The header is read right to left, skipping
trusted proxies, and the first other address wins; anything malformed falls
back to the peer address, never to an attacker-chosen value further left.
"""

import ipaddress
from collections.abc import Iterable
from functools import lru_cache

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def parse_trusted_proxies(raw: str) -> tuple[IPNetwork, ...]:
    """Comma-separated CIDRs; an invalid entry raises so a typo in the
    deployment config fails loudly at first use instead of silently trusting
    nothing (or everything)."""
    return tuple(ipaddress.ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip())


def _trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address, proxies: Iterable[IPNetwork]) -> bool:
    return any(address.version == network.version and address in network for network in proxies)


def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxies: tuple[IPNetwork, ...]) -> str:
    if not peer:
        return "unknown"
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not trusted_proxies or not _trusted(peer_address, trusted_proxies) or not forwarded_for:
        return peer
    for hop in reversed([part.strip() for part in forwarded_for.split(",")]):
        try:
            address = ipaddress.ip_address(hop)
        except ValueError:
            return peer
        if not _trusted(address, trusted_proxies):
            return str(address)
    return peer
