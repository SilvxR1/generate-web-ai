"""CloudflarePagesClient's domain methods + CloudflarePagesDomainProvider
against a mocked Cloudflare REST API (httpx.MockTransport — no real
account needed, same pattern as test_cloudflare_pages_publisher.py).
Covers attach's check-first idempotency, get_status for a domain that
was never attached, and detach's idempotency."""

import httpx
import pytest

from app.publishing.cloudflare import CloudflareApiError, CloudflarePagesClient, CloudflarePagesDomainProvider
from app.publishing.errors import WebsitePublisherError

ACCOUNT_ID = "acct-1"
API_TOKEN = "cf-super-secret-api-token"


def _provider(handler) -> CloudflarePagesDomainProvider:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://api.cloudflare.com/client/v4")
    client = CloudflarePagesClient(ACCOUNT_ID, API_TOKEN, http_client=http_client)
    return CloudflarePagesDomainProvider(client)


# --- attach -------------------------------------------------------------


def test_attach_creates_the_domain_when_not_already_attached():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"success": True, "result": {"name": "example.com", "status": "pending_dcv"}, "errors": []},
            )
        raise AssertionError(f"unexpected request: {request.method}")

    provider = _provider(handler)

    result = provider.attach(site_id="site-1", domain="example.com")

    assert result.domain == "example.com"
    assert result.provider_status == "pending_dcv"
    assert result.is_active is False
    assert result.cname_target == "site-1.pages.dev"
    assert [r.method for r in requests] == ["GET", "POST"]


def test_attach_is_idempotent_when_the_domain_is_already_attached():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"success": True, "result": {"name": "example.com", "status": "active"}, "errors": []}
            )
        raise AssertionError("must not attempt to re-create an already-attached domain")

    provider = _provider(handler)

    result = provider.attach(site_id="site-1", domain="example.com")

    assert result.is_active is True
    assert result.provider_status == "active"


def test_attach_rejects_an_invalid_site_id_before_any_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Cloudflare with an invalid project name")

    provider = _provider(handler)

    with pytest.raises(WebsitePublisherError):
        provider.attach(site_id="Not Valid!", domain="example.com")


def test_attach_propagates_a_creation_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        return httpx.Response(500, text="internal server error")

    provider = _provider(handler)

    with pytest.raises(CloudflareApiError):
        provider.attach(site_id="site-1", domain="example.com")


# --- get_status -----------------------------------------------------------


def test_get_status_reports_active_when_the_provider_says_active():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": True, "result": {"name": "example.com", "status": "active"}, "errors": []}
        )

    provider = _provider(handler)

    result = provider.get_status(site_id="site-1", domain="example.com")

    assert result.is_active is True
    assert result.provider_status == "active"


def test_get_status_for_a_domain_that_was_never_attached():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})

    provider = _provider(handler)

    result = provider.get_status(site_id="site-1", domain="example.com")

    assert result.is_active is False
    assert result.provider_status == "not_attached"
    assert result.error is not None


# --- detach -----------------------------------------------------------------


def test_detach_deletes_the_domain():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200, json={"success": True, "result": {"name": "example.com", "status": "active"}, "errors": []}
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={"success": True, "result": {"name": "example.com"}, "errors": []})
        raise AssertionError(f"unexpected request: {request.method}")

    provider = _provider(handler)

    provider.detach(site_id="site-1", domain="example.com")

    assert [r.method for r in requests] == ["GET", "DELETE"]


def test_detach_is_idempotent_when_the_domain_was_never_attached():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"success": False, "errors": [{"message": "not found"}]})
        raise AssertionError("must not attempt to delete a domain that isn't attached")

    provider = _provider(handler)

    provider.detach(site_id="site-1", domain="example.com")  # must not raise

    assert [r.method for r in requests] == ["GET"]
