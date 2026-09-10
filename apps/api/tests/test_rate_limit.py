"""InMemoryRateLimiter and rate_limit_dependency (Phase 5): the sliding
window itself, and that the asset-upload endpoint actually enforces it."""

import io

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.dependencies import get_rate_limiter, get_session
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter, RateLimitExceededError


def test_allows_up_to_the_limit_then_raises():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        limiter.check("key", limit=3, window_seconds=60)

    with pytest.raises(RateLimitExceededError):
        limiter.check("key", limit=3, window_seconds=60)


def test_keys_are_independent():
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        limiter.check("a", limit=3, window_seconds=60)

    limiter.check("b", limit=3, window_seconds=60)  # must not raise — separate key


def test_window_expiry_allows_new_attempts_after_it_passes():
    limiter = InMemoryRateLimiter()
    limiter.check("key", limit=1, window_seconds=0.05)
    with pytest.raises(RateLimitExceededError):
        limiter.check("key", limit=1, window_seconds=0.05)

    import time

    time.sleep(0.06)
    limiter.check("key", limit=1, window_seconds=0.05)  # must not raise — window elapsed


@pytest.fixture()
def client(session, tmp_path, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "asset_upload_rate_limit_per_minute", 2)

    # A single shared instance across every request in the test — the
    # lambda must not construct a fresh (and therefore always-empty)
    # limiter per call, or the count could never accumulate.
    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _upload(client: TestClient, business_id, tenant_id):
    return client.post(
        f"/businesses/{business_id}/assets/upload",
        headers={"X-Tenant-Id": str(tenant_id)},
        files={"file": ("logo.png", io.BytesIO(b"fake-bytes"), "image/png")},
        data={"kind": "image"},
    )


def test_asset_upload_is_rate_limited(client: TestClient, tenant, business):
    for _ in range(2):
        assert _upload(client, business.id, tenant.id).status_code == 201

    response = _upload(client, business.id, tenant.id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
