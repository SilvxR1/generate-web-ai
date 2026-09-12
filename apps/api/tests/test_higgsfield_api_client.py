"""HiggsfieldApiClient (app.creative.higgsfield.api_client) — every real
HTTP call replaced by httpx.MockTransport (no real network/credit spend
anywhere in this module). Verifies the auth header shape, submit/poll
request mapping, terminal-status handling, SSRF reference-URL validation,
and that a submit is never retried automatically."""

import httpx
import pytest

from app.creative.higgsfield.api_client import (
    DEFAULT_JOB_TYPE,
    HiggsfieldApiClient,
    HiggsfieldApiError,
    HiggsfieldApiUnavailableError,
)


def _client(handler) -> HiggsfieldApiClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.higgsfield.ai")
    return HiggsfieldApiClient(key_id="key-id", key_secret="key-secret", http_client=http_client)


def test_missing_credentials_raise_unavailable_before_any_request():
    with pytest.raises(HiggsfieldApiUnavailableError):
        HiggsfieldApiClient(key_id=None, key_secret=None)
    with pytest.raises(HiggsfieldApiUnavailableError):
        HiggsfieldApiClient(key_id="only-id", key_secret=None)


def test_submit_sends_the_documented_auth_header_shape():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "status": "queued",
                "request_id": "r-1",
                "status_url": "https://api.higgsfield.ai/requests/r-1/status",
                "cancel_url": "https://api.higgsfield.ai/requests/r-1/cancel",
            },
        )

    client = _client(handler)
    submitted = client.submit(DEFAULT_JOB_TYPE, prompt="a quiet alpine lake")

    assert captured["authorization"] == "Key key-id:key-secret"
    assert captured["path"] == "/nano-banana"
    assert submitted.request_id == "r-1"


def test_submit_never_retries_automatically_even_on_5xx():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="internal error")

    client = _client(handler)
    with pytest.raises(HiggsfieldApiError):
        client.submit(DEFAULT_JOB_TYPE, prompt="x")

    assert calls["count"] == 1  # never retried — a retried submit could double-spend credits


def test_submit_rejects_an_unknown_job_type_without_any_request():
    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, json={})

    client = _client(handler)
    with pytest.raises(HiggsfieldApiError):
        client.submit("nano-banana-pro", prompt="x")

    assert called["count"] == 0  # refused before any network call — no invented endpoint path


def test_submit_rejects_a_non_https_reference_url():
    client = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(HiggsfieldApiError):
        client.submit(DEFAULT_JOB_TYPE, prompt="x", image_references=["http://example.com/a.png"])


def test_submit_rejects_a_private_ip_reference_url():
    client = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(HiggsfieldApiError):
        client.submit(DEFAULT_JOB_TYPE, prompt="x", image_references=["https://127.0.0.1/a.png"])


def test_submit_caps_input_images_at_eight():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "queued",
                "request_id": "r-1",
                "status_url": "https://api.higgsfield.ai/requests/r-1/status",
                "cancel_url": "https://api.higgsfield.ai/requests/r-1/cancel",
            },
        )

    client = _client(handler)
    urls = [f"https://cdn.example.com/{i}.png" for i in range(12)]
    client.submit(DEFAULT_JOB_TYPE, prompt="x", image_references=urls)

    assert len(captured["body"]["input_images"]) == 8


def test_get_status_retries_on_timeout_then_succeeds():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectTimeout("boom", request=request)
        return httpx.Response(
            200, json={"status": "completed", "request_id": "r-1", "images": [{"url": "https://x/1.png"}]}
        )

    client = _client(handler)
    data = client.get_status("https://api.higgsfield.ai/requests/r-1/status")

    assert attempts["count"] == 3
    assert data["status"] == "completed"


def test_get_status_401_raises_unavailable():
    client = _client(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(HiggsfieldApiUnavailableError):
        client.get_status("https://api.higgsfield.ai/requests/r-1/status")


def test_create_polls_to_completion_and_returns_result_url():
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "status": "queued",
                    "request_id": "r-1",
                    "status_url": "https://api.higgsfield.ai/requests/r-1/status",
                    "cancel_url": "https://api.higgsfield.ai/requests/r-1/cancel",
                },
            ),
            httpx.Response(200, json={"status": "in_progress", "request_id": "r-1"}),
            httpx.Response(
                200, json={"status": "completed", "request_id": "r-1", "images": [{"url": "https://x/1.png"}]}
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = _client(handler)
    job = client.create(DEFAULT_JOB_TYPE, prompt="x", wait_timeout="30s")

    assert job.job_id == "r-1"
    assert job.status == "completed"
    assert job.result_url == "https://x/1.png"


def test_create_raises_on_failed_terminal_status():
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "status": "queued",
                    "request_id": "r-1",
                    "status_url": "https://api.higgsfield.ai/requests/r-1/status",
                    "cancel_url": "https://api.higgsfield.ai/requests/r-1/cancel",
                },
            ),
            httpx.Response(200, json={"status": "failed", "request_id": "r-1", "error": "moderation"}),
        ]
    )
    client = _client(lambda request: next(responses))
    with pytest.raises(HiggsfieldApiError):
        client.create(DEFAULT_JOB_TYPE, prompt="x", wait_timeout="30s")


def test_cancel_posts_to_the_cancel_url():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(204)

    client = _client(handler)
    client.cancel("https://api.higgsfield.ai/requests/r-1/cancel")

    assert captured["method"] == "POST"
    assert captured["path"] == "/requests/r-1/cancel"
