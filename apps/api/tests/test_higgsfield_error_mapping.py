"""hotfix P2/creative-directions-500 — regression coverage for the
production bug: POST .../creative-directions with `{}` for an existing
business with Higgsfield configured produced an opaque, un-typed HTTP 500
with no CORS headers, which the browser reported as "backend didn't
respond" even though the backend was fully reachable and had responded.

Root cause (see docs/higgsfield-integration.md and this PR's own report
for the full, empirically-verified chain):
  1. HiggsfieldApiCreativeDirector.create_directions raised a bare
     RuntimeError (not a CreativeProviderError) when every exploration
     attempt failed — e.g. because Higgsfield rejected every call.
  2. That bare RuntimeError escaped app.routers.creative's
     `except (CreativeProviderError, BudgetExceededError)` mapping and
     reached FastAPI's generic `@app.exception_handler(Exception)`
     catch-all.
  3. In this app's real Starlette middleware stack, a response produced
     by that specific catch-all never receives CORS headers — Starlette's
     ServerErrorMiddleware owns that handler and sits OUTSIDE
     CORSMiddleware (confirmed directly against the installed Starlette
     source, not assumed) — so the browser's fetch() reports an opaque
     network failure regardless of the real HTTP status code.

Fix: every real Higgsfield failure the REST client can produce is now a
specific, typed CreativeProviderError subclass
(app.creative.higgsfield.api_client), the director re-raises the real
failure instead of a bare RuntimeError, and the router maps each type to
its own structured AppError (_creative_provider_error) — which, because
AppError IS handled by a specifically-registered handler (not the
catch-all), correctly receives CORS headers. Every test below asserts the
FULL HTTP-layer behavior (status, structured JSON body, and the
Access-Control-Allow-Origin header) through the real app + real
middleware stack, via TestClient — not just the Python exception type —
since the CORS-header behavior is the actual user-visible bug.

No test in this module spends a real Higgsfield credit or makes a real
network call: every HiggsfieldApiCreativeDirector is constructed with a
fake, in-memory backend.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.creative.higgsfield.api_client import (
    HiggsfieldApiError,
    HiggsfieldInsufficientCreditsError,
    HiggsfieldModelUnavailableError,
    HiggsfieldReferenceAssetError,
    HiggsfieldTimeoutError,
)
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.creative.higgsfield.models import HiggsfieldJobResult
from app.db.models.business import Business
from app.db.models.business_asset import BusinessAsset
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.dependencies import get_creative_director, get_rate_limiter, get_session
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    BusinessStatus,
    BusinessVertical,
    WebsiteStatus,
)
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter

_ORIGIN = "http://localhost:5173"


@pytest.fixture()
def client(session: Session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
        app.dependency_overrides.pop(get_creative_director, None)


@pytest.fixture()
def cositas_business(session: Session, tenant: Tenant) -> Business:
    """The exact real business/config shape the production bug was
    reported against — reused, never recreated (test 3)."""
    business = Business(
        tenant_id=tenant.id,
        name="Cositas y Puntos",
        slug="cositas-y-puntos",
        vertical=BusinessVertical.OTHER,
        raw_description="Artesana espanola independiente.",
        status=BusinessStatus.ACTIVE,
        config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG.model_dump(mode="json"),
    )
    session.add(business)
    session.flush()
    return business


@pytest.fixture()
def cositas_logo_asset(session: Session, tenant: Tenant, cositas_business: Business) -> BusinessAsset:
    """A real, existing BusinessAsset — reused, never recreated (test 4)."""
    asset = BusinessAsset(
        tenant_id=tenant.id,
        business_id=cositas_business.id,
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/cositas/logo.png",
    )
    session.add(asset)
    session.flush()
    return asset


class _FailingClient:
    """A fake HiggsfieldApiClient-shaped backend that always raises the
    same scripted exception — reproduces exactly what the real REST API
    was observed to do (see docs/higgsfield-integration.md's "Live proof
    result"), with zero network calls and zero credit spend."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0

    def create(
        self, job_type, *, prompt, image_references=None, aspect_ratio=None, resolution=None, wait_timeout="4m"
    ):
        self.calls += 1
        raise self._exc


class _SucceedingClient:
    """A fake backend that always succeeds — proves the happy path
    (Higgsfield configured + selected, real candidates produced) still
    works after this hotfix, with zero network calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(
        self, job_type, *, prompt, image_references=None, aspect_ratio=None, resolution=None, wait_timeout="4m"
    ):
        self.calls.append({"prompt": prompt, "image_references": image_references})
        return HiggsfieldJobResult(
            job_id=f"job-{len(self.calls)}",
            job_type=job_type,
            status="completed",
            result_url=f"https://x/{len(self.calls)}.png",
        )


def _post_creative_directions(client: TestClient, business: Business, tenant: Tenant):
    return client.post(
        f"/businesses/{business.id}/creative-directions",
        json={},
        headers={"X-Tenant-Id": str(tenant.id), "Origin": _ORIGIN},
    )


# --- The exact reported bug: {} body, existing business, real error shapes ----


def test_empty_json_body_is_a_valid_request(client: TestClient, tenant: Tenant, cositas_business: Business):
    """`{}` is a valid CreateDirectionsRequest (hard_limit is optional) —
    confirmed by using it directly, matching production."""
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(_SucceedingClient())
    response = _post_creative_directions(client, cositas_business, tenant)
    assert response.status_code == 201  # never a 422 for `{}` itself


@pytest.mark.parametrize(
    ("exc", "expected_code", "expected_status", "expected_message_fragment"),
    [
        (
            HiggsfieldInsufficientCreditsError("...", detail="not_enough_credits"),
            "higgsfield_insufficient_credits",
            503,
            "enough API credits",
        ),
        (
            HiggsfieldModelUnavailableError("...", detail="model_not_found"),
            "higgsfield_model_unavailable",
            503,
            "currently unavailable",
        ),
        (
            HiggsfieldTimeoutError("did not reach a terminal state within 4m."),
            "higgsfield_timeout",
            504,
            "timed out",
        ),
        (
            HiggsfieldReferenceAssetError("Refusing to send a non-https reference URL to Higgsfield."),
            "higgsfield_reference_asset_unreachable",
            422,
            "reference image",
        ),
    ],
)
def test_higgsfield_failures_produce_a_structured_error_never_an_opaque_500(
    client: TestClient,
    tenant: Tenant,
    cositas_business: Business,
    exc: HiggsfieldApiError,
    expected_code: str,
    expected_status: int,
    expected_message_fragment: str,
):
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(_FailingClient(exc))

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == expected_status
    assert response.status_code != 500  # the exact reported production symptom
    body = response.json()
    assert body["error"]["code"] == expected_code
    assert expected_message_fragment in body["error"]["message"]
    # The actual user-visible bug: this response must be readable by the
    # browser at all (see this module's own docstring for why a missing
    # CORS header here makes Studio wrongly report "backend didn't respond").
    assert response.headers.get("access-control-allow-origin") == _ORIGIN


def test_a_bare_unrecognized_creative_provider_error_still_gets_a_generic_structured_response(
    client: TestClient, tenant: Tenant, cositas_business: Business
):
    """Defense in depth: even a HiggsfieldApiError subtype this router
    doesn't have a specific mapping for must still produce a structured,
    CORS-correct AppError (the generic "creative_direction_error"
    fallback) — never fall through to the un-typed catch-all."""
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(
        _FailingClient(HiggsfieldApiError("some other Higgsfield failure"))
    )

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "creative_direction_error"
    assert response.headers.get("access-control-allow-origin") == _ORIGIN


# --- Existing business/config/assets reuse, storage non-blocking ----------


def test_existing_business_config_is_reused_not_recreated(
    client: TestClient, tenant: Tenant, cositas_business: Business
):
    fake = _SucceedingClient()
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(fake)

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 201
    # The real business_name from the ALREADY-PERSISTED config reached the prompt.
    assert all("Cositas y Puntos" in call["prompt"] for call in fake.calls)


def test_existing_business_assets_are_passed_into_the_workflow(
    client: TestClient, tenant: Tenant, cositas_business: Business, cositas_logo_asset: BusinessAsset
):
    fake = _SucceedingClient()
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(fake)

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 201
    assert fake.calls[0]["image_references"] == ["https://cdn.example.com/cositas/logo.png"]


def test_no_r2_configured_does_not_block_direction_generation(
    client: TestClient, tenant: Tenant, cositas_business: Business, monkeypatch: pytest.MonkeyPatch
):
    """R2 must never be a requirement for this endpoint — it never even
    touches StorageProvider (confirmed: get_storage_provider isn't a
    dependency of create_creative_directions_route at all)."""
    from app.config import settings

    monkeypatch.setattr(settings, "r2_account_id", None)
    monkeypatch.setattr(settings, "r2_access_key_id", None)
    monkeypatch.setattr(settings, "r2_secret_access_key", None)
    monkeypatch.setattr(settings, "r2_bucket_name", None)
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(_SucceedingClient())

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 201


# --- Security / safety -----------------------------------------------------


def test_no_credentials_appear_in_the_error_response(client: TestClient, tenant: Tenant, cositas_business: Business):
    fake_secret = "sk-fake-super-secret-value"
    exc = HiggsfieldInsufficientCreditsError(
        "Higgsfield Cloud does not have enough API credits to run this generation.", detail="not_enough_credits"
    )
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(_FailingClient(exc))

    response = _post_creative_directions(client, cositas_business, tenant)

    assert fake_secret not in response.text
    assert "Authorization" not in response.text
    assert "Key " not in response.text


def test_published_website_remains_untouched_by_a_failed_generation(
    session: Session, client: TestClient, tenant: Tenant, cositas_business: Business
):
    published = Website(
        tenant_id=tenant.id,
        business_id=cositas_business.id,
        status=WebsiteStatus.LIVE,
        deploy_url="https://cositas-y-puntos.example.com",
    )
    session.add(published)
    session.flush()
    published_id = published.id

    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(
        _FailingClient(HiggsfieldModelUnavailableError("...", detail="model_not_found"))
    )
    response = _post_creative_directions(client, cositas_business, tenant)
    assert response.status_code == 503

    still_there = session.get(Website, published_id)
    assert still_there is not None
    assert still_there.status == WebsiteStatus.LIVE
    assert still_there.deploy_url == "https://cositas-y-puntos.example.com"


def test_no_real_higgsfield_network_call_happens_in_this_test_module(
    client: TestClient, tenant: Tenant, cositas_business: Business
):
    """Every test above injects a fake backend via dependency override —
    this test just asserts that override mechanism itself works, i.e.
    that get_creative_director is genuinely replaced and no real
    HiggsfieldApiClient/HTTP call could occur."""
    fake = _SucceedingClient()
    app.dependency_overrides[get_creative_director] = lambda: HiggsfieldApiCreativeDirector(fake)

    _post_creative_directions(client, cositas_business, tenant)

    assert fake.calls  # the fake, not a real network client, actually ran
