"""Thin wrapper over the Cloudflare Pages REST calls
CloudflarePagesPublisher still needs for project lookup/creation and
post-deploy status/metadata — never for uploading file content. Every
method either returns Cloudflare's parsed JSON `result` or raises
CloudflareApiError — nothing is ever silently swallowed into a fake
success.

Asset upload used to go through this client too (a raw REST direct-
upload implementation: an upload-token JWT, `check-missing`, `upload`,
`upsert-hashes`). Confirmed live against a real account, that path *did*
eventually reach a state where Cloudflare's own API reported every
asset present and the deployment "success" — and the live URL still
500'd on every request, with no further diagnostic surface available
through the API. Cloudflare's own guidance is to use Wrangler for
direct-upload of prebuilt assets, so
CloudflarePagesPublisher.publish() now shells out to
`wrangler pages deploy` for that step instead (see engine.py) — this
client's role shrank to what the REST API is actually reliable for:
project existence/creation and reading back status after the fact.
"""

from typing import Any

import httpx

from app.publishing.errors import WebsitePublisherError


class CloudflareApiError(WebsitePublisherError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CloudflarePagesClient:
    def __init__(self, account_id: str, api_token: str, *, http_client: httpx.Client | None = None) -> None:
        # `_auth_headers` is applied per-request (not baked into
        # `http_client`'s own defaults) so that injecting a custom
        # `http_client` — e.g. one wired to httpx.MockTransport in tests
        # — still exercises the real header-setting behavior instead of
        # silently skipping it. Same pattern as N8nClient.
        self._client = http_client or httpx.Client(base_url="https://api.cloudflare.com/client/v4", timeout=30.0)
        self._account_id = account_id
        self._auth_headers = {"Authorization": f"Bearer {api_token}"}

    def ensure_project(self, project_name: str) -> None:
        """Idempotent: checks for the project first (a plain GET, no
        ambiguity about interpreting a provider-specific "already
        exists" error code) and only creates it if missing."""
        if self._project_exists(project_name):
            return
        self._request(
            "POST",
            f"/accounts/{self._account_id}/pages/projects",
            json={"name": project_name, "production_branch": "production"},
        )

    def get_project(self, project_name: str) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{self._account_id}/pages/projects/{project_name}")

    def _project_exists(self, project_name: str) -> bool:
        response = self._client.get(
            f"/accounts/{self._account_id}/pages/projects/{project_name}", headers=self._auth_headers
        )
        return response.status_code == 200

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # Deliberately no logging of `kwargs` or of headers (holds the
        # API token) — nothing here is logged at all, so there's
        # nothing for a secret to leak into.
        headers = {**self._auth_headers, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise CloudflareApiError(f"Cloudflare request failed: {exc}") from exc

        if response.status_code >= 400:
            raise CloudflareApiError(
                f"Cloudflare returned {response.status_code} for {method} {path}: {response.text}",
                status_code=response.status_code,
            )

        body = response.json()
        if not body.get("success", False):
            raise CloudflareApiError(
                f"Cloudflare reported failure for {method} {path}: {body.get('errors')}",
                status_code=response.status_code,
            )
        return body.get("result") or {}
