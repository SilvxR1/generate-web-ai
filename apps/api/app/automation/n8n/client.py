"""Thin wrapper over n8n's REST API. No translation logic here (see
translator.py), no retry/queueing (NO Redis — nothing here needs async
processing, each call is a single synchronous request/response). Every
method either returns n8n's parsed JSON response or raises N8nApiError —
nothing is ever silently swallowed into a fake success.
"""

from typing import Any

import httpx

from app.automation.errors import AutomationEngineError


class N8nApiError(AutomationEngineError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class N8nClient:
    def __init__(self, base_url: str, api_key: str, *, http_client: httpx.Client | None = None) -> None:
        # `_auth_headers` is applied per-request (not baked into
        # `http_client`'s own defaults) so that injecting a custom
        # `http_client` — e.g. one wired to httpx.MockTransport in tests
        # — still exercises the real header-setting behavior instead of
        # silently skipping it.
        self._client = http_client or httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0)
        self._auth_headers = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}

    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/workflows", json=payload)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        # n8n's real API rejects PATCH here ("PATCH method not allowed")
        # — full replace via PUT is the only supported method.
        return self._request("PUT", f"/api/v1/workflows/{workflow_id}", json=payload)

    def activate_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/workflows/{workflow_id}/activate")

    def deactivate_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/workflows/{workflow_id}/deactivate")

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/executions/{execution_id}")

    def list_executions(self, workflow_id: str) -> dict[str, Any]:
        return self._request("GET", "/api/v1/executions", params={"workflowId": workflow_id})

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        # Deliberately no logging of `kwargs` (may contain the workflow
        # payload) or of headers (holds the API key) — nothing here is
        # logged at all, so there's nothing for a secret to leak into.
        headers = {**self._auth_headers, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise N8nApiError(f"n8n request failed: {exc}") from exc

        if response.status_code >= 400:
            raise N8nApiError(
                f"n8n returned {response.status_code} for {method} {path}: {response.text}",
                status_code=response.status_code,
            )

        if not response.content:
            return {}
        return response.json()
