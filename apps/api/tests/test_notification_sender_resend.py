"""ResendNotificationSender against a mocked HTTPS transport
(httpx.MockTransport — no real network, no real email ever sent): a
successful send posts the expected JSON body and Bearer-auth header to
Resend's /emails endpoint; a 4xx/5xx response or a transport-level
failure becomes a NotificationSenderError that never leaks the API key,
same "provider error, secret safety" coverage as
test_notification_sender_smtp.py's for SMTP."""

import httpx
import pytest

from app.notifications.errors import NotificationSenderError
from app.notifications.resend import ResendApiError, ResendNotificationSender
from app.notifications.sender import NotificationEmail

API_KEY = "re_super_secret_resend_api_key"
FROM_ADDRESS = "notificaciones@generate-web-ai.example"


def _sender(handler, **overrides: object) -> ResendNotificationSender:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.resend.com")
    kwargs: dict[str, object] = {"api_key": API_KEY, "from_address": FROM_ADDRESS, "http_client": http_client}
    kwargs.update(overrides)
    return ResendNotificationSender(**kwargs)


def _message() -> NotificationEmail:
    return NotificationEmail(to="business@example.com", subject="Nuevo lead", body="Juan Perez — +34600000000")


# --- successful send ---------------------------------------------------------


def test_send_posts_the_expected_request():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "email-123"})

    _sender(handler).send(_message())

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/emails"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    body = httpx.Response(200, content=request.content).json()
    assert body == {
        "from": FROM_ADDRESS,
        "to": ["business@example.com"],
        "subject": "Nuevo lead",
        "text": "Juan Perez — +34600000000",
    }


def test_send_does_not_raise_on_a_2xx_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"id": "email-456"})

    _sender(handler).send(_message())  # no exception


# --- provider errors ----------------------------------------------------------


def test_4xx_response_becomes_a_notification_sender_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"name": "validation_error", "message": "Invalid `from` field."})

    with pytest.raises(NotificationSenderError) as exc_info:
        _sender(handler).send(_message())

    assert isinstance(exc_info.value, ResendApiError)
    assert exc_info.value.status_code == 422


def test_5xx_response_becomes_a_notification_sender_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"name": "internal_server_error", "message": "Something went wrong."})

    with pytest.raises(NotificationSenderError):
        _sender(handler).send(_message())


def test_transport_failure_becomes_a_notification_sender_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(NotificationSenderError):
        _sender(handler).send(_message())


# --- secret safety -------------------------------------------------------------


def test_provider_error_never_leaks_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"name": "unauthorized", "message": "Invalid API key."})

    with pytest.raises(NotificationSenderError) as exc_info:
        _sender(handler).send(_message())

    assert API_KEY not in str(exc_info.value)


def test_transport_failure_never_leaks_the_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(NotificationSenderError) as exc_info:
        _sender(handler).send(_message())

    assert API_KEY not in str(exc_info.value)
