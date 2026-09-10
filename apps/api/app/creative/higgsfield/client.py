"""Minimal authenticated-HTTP building block for a future Higgsfield
integration. Deliberately generic — a bearer-token request helper, no
Higgsfield-specific endpoint paths or payload shapes — because inspecting
this repository and its available tooling while building this feature
turned up no real Higgsfield SDK, REST client, or MCP server to implement
against, and Section 10 of the master context explicitly forbids inventing
one. Mirrors app.publishing.cloudflare.client.CloudflarePagesClient's
constructor shape (per-request auth headers, an injectable httpx.Client
for tests) so wiring real endpoints later is a matter of adding methods
here, not building request plumbing from scratch.
"""

from typing import Any

import httpx


class HiggsfieldClient:
    def __init__(self, api_key: str, base_url: str, *, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(base_url=base_url, timeout=60.0)
        self._auth_headers = {"Authorization": f"Bearer {api_key}"}

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Generic authenticated request. Not called by
        HiggsfieldCreativeProvider today — see that module's docstring
        for why — kept here so a real endpoint contract can be wired in
        as a small, additive change once Higgsfield's actual API
        documentation is available, never logs `headers` or any
        credential."""
        headers = {**self._auth_headers, **kwargs.pop("headers", {})}
        return self._client.request(method, path, headers=headers, **kwargs)
