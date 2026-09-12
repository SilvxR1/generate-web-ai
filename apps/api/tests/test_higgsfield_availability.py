"""check_higgsfield_director_availability (app.creative.higgsfield.availability)
— httpx.get monkeypatched throughout (no real network/credit spend). Never
calls a generation endpoint; only ever probes GET /requests/<uuid>/status."""

import httpx
import pytest

from app.config import Settings
from app.creative.higgsfield.availability import check_higgsfield_director_availability


def test_unavailable_when_key_pair_not_configured():
    settings = Settings(higgsfield_api_key_id=None, higgsfield_api_key_secret=None)  # type: ignore[call-arg]
    available, reason = check_higgsfield_director_availability(settings)
    assert available is False
    assert "not configured" in reason


def test_unavailable_when_only_half_the_pair_is_configured():
    settings = Settings(higgsfield_api_key_id="id-only", higgsfield_api_key_secret=None)  # type: ignore[call-arg]
    available, reason = check_higgsfield_director_availability(settings)
    assert available is False


def test_unavailable_when_key_pair_is_rejected(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(higgsfield_api_key_id="bad-id", higgsfield_api_key_secret="bad-secret")  # type: ignore[call-arg]

    def fake_get(url, *, headers, timeout):
        return httpx.Response(401, json={"error": "unauthorized"}, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.creative.higgsfield.availability.httpx.get", fake_get)
    available, reason = check_higgsfield_director_availability(settings)

    assert available is False
    assert "rejected" in reason
    assert "bad-secret" not in reason  # never leaks the secret


def test_available_when_key_pair_is_accepted_even_via_a_404(monkeypatch: pytest.MonkeyPatch):
    """A made-up request id should 404 (not found), never fail
    authentication — this non-401 outcome is exactly how the probe proves
    the key pair itself works without spending a credit."""
    settings = Settings(higgsfield_api_key_id="real-id", higgsfield_api_key_secret="real-secret")  # type: ignore[call-arg]

    def fake_get(url, *, headers, timeout):
        assert headers["Authorization"] == "Key real-id:real-secret"
        return httpx.Response(404, json={"error": "not found"}, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.creative.higgsfield.availability.httpx.get", fake_get)
    available, reason = check_higgsfield_director_availability(settings)

    assert available is True
    assert reason is None


def test_unavailable_on_network_error(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(higgsfield_api_key_id="real-id", higgsfield_api_key_secret="real-secret")  # type: ignore[call-arg]

    def fake_get(url, *, headers, timeout):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    monkeypatch.setattr("app.creative.higgsfield.availability.httpx.get", fake_get)
    available, reason = check_higgsfield_director_availability(settings)

    assert available is False
    assert "Could not reach" in reason
