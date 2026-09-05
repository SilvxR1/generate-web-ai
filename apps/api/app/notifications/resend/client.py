"""ResendNotificationSender — a cloud-safe HTTP NotificationSender
implementation: delivers over HTTPS to Resend's REST API
(https://api.resend.com/emails) instead of opening a raw SMTP socket,
which most serverless/edge runtimes either block outbound or make
unreliable. One more replaceable NotificationSender (see sender.py's
docstring) — nothing outside this module knows Resend's request/response
shape, same boundary SmtpNotificationSender (app.notifications.smtp)
already established for SMTP.
"""

from typing import Any

import httpx

from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender

_RESEND_API_BASE_URL = "https://api.resend.com"


class ResendApiError(NotificationSenderError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ResendNotificationSender(NotificationSender):
    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        http_client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        # `_auth_headers` is applied per-request (not baked into
        # `http_client`'s own defaults) so that injecting a custom
        # `http_client` — e.g. one wired to httpx.MockTransport in tests
        # — still exercises the real header-setting behavior instead of
        # silently skipping it. Same pattern as N8nClient/CloudflarePagesClient.
        self._client = http_client or httpx.Client(base_url=_RESEND_API_BASE_URL, timeout=timeout)
        self._from_address = from_address
        self._auth_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def send(self, message: NotificationEmail) -> None:
        payload: dict[str, Any] = {
            "from": self._from_address,
            "to": [message.to],
            "subject": message.subject,
            "text": message.body,
        }
        # Deliberately no logging of `payload` or of headers (holds the
        # API key) — nothing here is logged at all, so there's nothing
        # for a secret to leak into.
        try:
            response = self._client.post("/emails", json=payload, headers=self._auth_headers)
        except httpx.HTTPError as exc:
            # httpx's own exception text describes the request/connection
            # failure (timeout, DNS, ...), never the headers it sent — so
            # this never carries the API key either.
            raise ResendApiError(f"Resend request failed: {exc}") from exc

        if response.status_code >= 400:
            # Resend's error body describes what was wrong with *our
            # request* (invalid `from`/`to`, rate limit, ...); it never
            # echoes back the Authorization header, so response.text
            # carries no secret.
            raise ResendApiError(
                f"Resend returned {response.status_code}: {response.text}",
                status_code=response.status_code,
            )
