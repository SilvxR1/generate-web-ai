"""A3 F-03 remediation: POST .../creative-generations, .../creative-
directions, and .../creative-directions/{id}/develop each trigger a real
Higgsfield/Anthropic provider call and previously had no rate limit at
all — only an authenticated session + TenantAccess grant and, per
request, CreativeBudget's own fan-out cap, neither of which bounds how
often a caller can invoke them per minute. This file proves the new
rate_limit_dependency wiring (same infrastructure as login/asset-upload/
website-health/public-lead/public-analytics) actually works, without ever
calling a real provider — generation at BASIC level is satisfied by the
free InternalCreativeProvider (app.creative.internal), never Higgsfield
or Anthropic.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.creative.internal import InternalCreativeProvider
from app.creative.provider import CreativeGenerationResult
from app.db.models.tenant import Tenant
from app.dependencies import get_internal_creative_provider, get_rate_limiter, get_session
from app.domain.creative import CreativeBrief
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter


class _CountingInternalProvider(InternalCreativeProvider):
    """Wraps the real, free internal provider — counts invocations so a
    test can assert the provider is never called for a request the rate
    limiter already rejected."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_concept(self, brief: CreativeBrief) -> CreativeGenerationResult:
        self.calls += 1
        return super().generate_concept(brief)

    def generate_website(self, brief: CreativeBrief) -> CreativeGenerationResult:
        self.calls += 1
        return super().generate_website(brief)


@pytest.fixture()
def counting_provider() -> _CountingInternalProvider:
    return _CountingInternalProvider()


@pytest.fixture()
def client(session, counting_provider: _CountingInternalProvider, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    # A tight, deterministic limit for fast tests — the real production
    # default (app.config.Settings.creative_generation_rate_limit_per_minute)
    # is exercised structurally here (same dependency, same settings
    # attribute), just at a smaller number so a test doesn't need to make
    # 5+ requests to observe a rejection.
    monkeypatch.setattr(settings, "creative_generation_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "creative_direction_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "creative_direction_develop_rate_limit_per_minute", 2)

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_internal_creative_provider] = lambda: counting_provider
    # A single shared limiter instance across every request THIS test
    # makes (see tests/test_rate_limit.py's own client fixture for the
    # same precedent — a fresh-per-call lambda would never accumulate a
    # count at all).
    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_internal_creative_provider, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def _business_config_payload() -> dict:
    return {
        "schema_version": 1,
        "business_profile": {"name": "Sacri Barber", "slug": "sacri-barber", "industry": "other"},
    }


def _create_business(client: TestClient, tenant_id: uuid.UUID) -> dict:
    payload = {
        "name": "Sacri Barber",
        "slug": "sacri-barber",
        "vertical": "other",
        "raw_description": "Barberia clasica en el centro de la ciudad con mas de cinco anos.",
        "status": "draft",
        "config": _business_config_payload(),
    }
    response = client.post("/businesses", json=payload, headers=_headers(tenant_id))
    assert response.status_code == 201, response.text
    return response.json()


def _generate(client: TestClient, business_id: str, tenant_id: uuid.UUID):
    return client.post(
        f"/businesses/{business_id}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(tenant_id),
    )


def test_normal_authorized_calls_within_the_limit_succeed(
    client: TestClient, tenant: Tenant, counting_provider: _CountingInternalProvider
):
    business = _create_business(client, tenant.id)

    first = _generate(client, business["id"], tenant.id)
    second = _generate(client, business["id"], tenant.id)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert counting_provider.calls == 2


def test_repeated_calls_eventually_receive_429_and_the_provider_is_never_invoked_after(
    client: TestClient, tenant: Tenant, counting_provider: _CountingInternalProvider
):
    business = _create_business(client, tenant.id)

    responses = [_generate(client, business["id"], tenant.id) for _ in range(4)]

    statuses = [r.status_code for r in responses]
    assert statuses == [201, 201, 429, 429], statuses
    assert responses[2].json()["error"]["code"] == "rate_limited"

    # The real security property: the provider (Higgsfield/Anthropic in
    # production, the free internal one here) was invoked exactly twice
    # — never for either of the two rejected requests. A rate limit that
    # still let the expensive work happen before rejecting the response
    # would protect nothing.
    assert counting_provider.calls == 2


def test_tenant_authorization_is_still_enforced_alongside_the_rate_limit(
    client: TestClient, counting_provider: _CountingInternalProvider
):
    """Adding a rate limit must never weaken or bypass tenant
    authorization: a request naming a tenant that doesn't exist at all
    is still rejected by get_current_tenant_id itself, never silently
    treated as authorized just because it happened to also be within
    the rate-limit budget."""
    unknown_tenant_id = uuid.uuid4()

    response = client.post(
        f"/businesses/{uuid.uuid4()}/creative-generations",
        json={"generation_type": "website"},
        headers=_headers(unknown_tenant_id),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"
    assert counting_provider.calls == 0


def test_rate_limit_applies_per_request_including_ones_that_fail_the_business_lookup(
    client: TestClient, tenant: Tenant, counting_provider: _CountingInternalProvider
):
    """The rate limiter is a per-request gate ahead of the route body —
    it applies uniformly whether or not that particular request would
    also have failed for an unrelated reason (here, an unknown
    business_id under an otherwise-valid, authorized tenant). This is
    the correct, conservative behavior: a caller cannot get "free"
    (unrate-limited) attempts just by targeting a business_id that
    happens not to exist."""
    unknown_business_id = uuid.uuid4()

    responses = [_generate(client, str(unknown_business_id), tenant.id) for _ in range(4)]

    statuses = [r.status_code for r in responses]
    assert statuses[:2] == [404, 404]
    assert statuses[2:] == [429, 429]
    assert counting_provider.calls == 0


def test_public_caller_with_no_tenant_context_cannot_reach_the_endpoint(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    response = client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website"},
        # No X-Tenant-Id header at all — an anonymous caller has no way
        # to name a tenant to begin with, let alone an authorized one.
        headers={},
    )

    assert response.status_code == 422
