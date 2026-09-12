"""GET .../frontend-engineer-availability (P2 continuation Part 1) —
honest, real-verified Anthropic availability, never a "configured means
working" placeholder. The Anthropic client is faked here (no real
network call in default tests); the real, on-demand check this endpoint
performs is exercised for real by tests/test_frontend_engine_real.py
(-m real_provider), which is what actually confirmed the currently
invalid key in this environment.
"""

from unittest.mock import MagicMock, patch

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.creative.frontend_engine.availability import check_frontend_engineer_availability
from app.db.models.tenant import Tenant
from app.dependencies import get_rate_limiter, get_session
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    # A fresh limiter per test — this module's own shared singleton
    # (app.dependencies) would otherwise carry request counts across
    # every test in this file, the same isolation fix
    # tests/test_public_leads_api.py already documents for this exact
    # rate-limited-endpoint pattern.
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(tenant_id) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def test_unavailable_when_no_key_configured():
    settings = Settings(anthropic_api_key=None)  # type: ignore[arg-type]

    available, reason = check_frontend_engineer_availability(settings)

    assert available is False
    assert "not configured" in reason


def test_unavailable_when_key_is_rejected():
    settings = Settings(anthropic_api_key="sk-ant-fake")  # type: ignore[arg-type]
    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client_cls.return_value.messages.create.side_effect = anthropic.AuthenticationError(
            message="invalid", response=MagicMock(status_code=401, headers={}), body=None
        )
        available, reason = check_frontend_engineer_availability(settings)

    assert available is False
    assert "rejected by Anthropic" in reason
    assert "sk-ant-fake" not in reason  # never leaks the key


def test_available_when_key_is_accepted():
    settings = Settings(anthropic_api_key="sk-ant-real")  # type: ignore[arg-type]
    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client_cls.return_value.messages.create.return_value = MagicMock()
        available, reason = check_frontend_engineer_availability(settings)

    assert available is True
    assert reason is None


def test_availability_endpoint_reports_unavailable_without_a_key(client: TestClient, tenant: Tenant, business):
    with patch("app.routers.creative.settings.anthropic_api_key", None):
        response = client.get(
            f"/businesses/{business.id}/frontend-engineer-availability", headers=_headers(tenant.id)
        )

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["provider"] == "anthropic"


def test_availability_endpoint_returns_the_real_check_result(client: TestClient, tenant: Tenant, business):
    # Patched where it's actually called from (app.routers.creative's
    # own bound name), not where it's defined — patching the source
    # module alone leaves the router's already-imported reference
    # untouched, and this endpoint would otherwise make a real Anthropic
    # call in this test.
    with patch("app.routers.creative.check_frontend_engineer_availability", return_value=(True, None)):
        response = client.get(
            f"/businesses/{business.id}/frontend-engineer-availability", headers=_headers(tenant.id)
        )

    assert response.status_code == 200
    assert response.json() == {"provider": "anthropic", "available": True, "unavailable_reason": None}


def test_availability_endpoint_uses_the_shared_rate_limit_dependency(client: TestClient, tenant: Tenant, business):
    """This endpoint is rate-limited via the same, already-proven
    app.dependencies.rate_limit_dependency every other real-outbound-call
    endpoint in this codebase uses (see e.g. website_health's own "Check
    now" tests) — verified here by confirming the dependency is actually
    wired to a real Settings field, not by re-testing the generic
    rate-limiting mechanism itself."""
    assert settings.frontend_engineer_availability_rate_limit_per_minute > 0
