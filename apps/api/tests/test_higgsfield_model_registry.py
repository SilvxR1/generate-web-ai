"""app.creative.higgsfield.api_client's HiggsfieldModelConfig/_MODEL_REGISTRY
— the P2.1-continuation fix for the production blocker where the
Creative Director was hardcoded to `POST /nano-banana` (404
model_not_found on this workspace) with no way to switch models without a
code change. Every real HTTP call is replaced by httpx.MockTransport (no
real network/credit spend anywhere in this module), same pattern as
test_higgsfield_api_client.py."""

import json

import httpx
import pytest

from app.creative.higgsfield.api_client import (
    DEFAULT_JOB_TYPE,
    HiggsfieldApiClient,
    HiggsfieldApiUnavailableError,
    HiggsfieldModelConfig,
    resolve_model_config,
)


def _client(handler) -> HiggsfieldApiClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.higgsfield.ai")
    return HiggsfieldApiClient(key_id="key-id", key_secret="key-secret", http_client=http_client)


def _accepted(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "queued",
            "request_id": "r-1",
            "status_url": "https://api.higgsfield.ai/requests/r-1/status",
            "cancel_url": "https://api.higgsfield.ai/requests/r-1/cancel",
        },
    )


# --- 1. configured Higgsfield model selection -------------------------------


def test_configured_model_selects_its_own_registered_endpoint():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return _accepted(request)

    client = _client(handler)
    client.submit(
        "higgsfield-ai/soul/reference", prompt="x", image_references=["https://cdn.example.com/logo.png"]
    )

    assert captured["path"] == "/higgsfield-ai/soul/reference"
    # This model's own schema field, never nano-banana's `input_images`.
    assert captured["body"]["image_reference_url"] == "https://cdn.example.com/logo.png"
    assert "input_images" not in captured["body"]


def test_default_model_is_still_nano_banana_unless_overridden():
    assert DEFAULT_JOB_TYPE == "nano-banana"
    assert resolve_model_config(DEFAULT_JOB_TYPE).endpoint == "/nano-banana"


# --- 2. unsupported configured model rejected safely ------------------------


def test_unsupported_configured_model_is_rejected_before_any_request():
    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, json={})

    client = _client(handler)
    with pytest.raises(HiggsfieldApiUnavailableError):
        client.submit("totally-fake-model", prompt="x")

    assert called["count"] == 0  # refused before any network call — no invented endpoint path


def test_resolve_model_config_rejects_an_unregistered_id_safely():
    # Never a bare KeyError/AttributeError — a structured, catchable error
    # app.creative.director_fallback treats as pre-acceptance-safe.
    with pytest.raises(HiggsfieldApiUnavailableError):
        resolve_model_config("higgsfield-ai/nano-banana-pro")


# --- 3. endpoint comes from allowlist, never an arbitrary URL ---------------


@pytest.mark.parametrize(
    "malicious_model_id",
    [
        "https://evil.example.com/steal",
        "../../../etc/passwd",
        "/nano-banana/../../internal",
        "",
    ],
)
def test_submit_never_builds_a_path_from_an_unrecognized_model_id(malicious_model_id: str):
    called = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["count"] += 1
        return httpx.Response(200, json={})

    client = _client(handler)
    with pytest.raises(HiggsfieldApiUnavailableError):
        client.submit(malicious_model_id, prompt="x")

    assert called["count"] == 0  # only a dict .get() lookup ever runs — never a constructed URL


def test_every_registered_endpoint_is_a_real_absolute_path_never_derived_from_the_model_id():
    from app.creative.higgsfield.api_client import _MODEL_REGISTRY  # noqa: PLC0415 — test-only introspection

    for model_id, config in _MODEL_REGISTRY.items():
        assert config.endpoint.startswith("/")
        assert ".." not in config.endpoint
        # The registry is a real allowlist, not "endpoint == model_id" —
        # confirmed by construction, not by string-deriving one from the
        # other anywhere in submit().
        assert isinstance(config, HiggsfieldModelConfig)
        assert config.id == model_id


# --- 4. reference-image capability per model --------------------------------


def test_nano_banana_sends_up_to_eight_input_images_as_an_array():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _accepted(request)

    client = _client(handler)
    urls = [f"https://cdn.example.com/{i}.png" for i in range(12)]
    client.submit(DEFAULT_JOB_TYPE, prompt="x", image_references=urls)

    assert len(captured["body"]["input_images"]) == 8
    assert captured["body"]["input_images"][0] == {"type": "image_url", "image_url": urls[0]}


def test_soul_reference_sends_exactly_one_image_reference_url_even_if_more_are_given():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _accepted(request)

    client = _client(handler)
    urls = ["https://cdn.example.com/logo.png", "https://cdn.example.com/hero.png"]
    client.submit("higgsfield-ai/soul/reference", prompt="x", image_references=urls)

    assert captured["body"]["image_reference_url"] == urls[0]
    assert "input_images" not in captured["body"]


def test_a_model_with_no_reference_support_never_receives_a_reference_field():
    config = HiggsfieldModelConfig(
        id="text-only",
        endpoint="/text-only",
        supports_reference_images=False,
        max_reference_images=0,
        supported_aspect_ratios=frozenset({"1:1"}),
        reference_image_param=None,
    )
    assert config.build_reference_payload(["https://cdn.example.com/logo.png"]) == {}


def test_no_reference_urls_produces_no_reference_field_for_either_model():
    for model_id in ("nano-banana", "higgsfield-ai/soul/reference"):
        config = resolve_model_config(model_id)
        assert config.build_reference_payload([]) == {}
