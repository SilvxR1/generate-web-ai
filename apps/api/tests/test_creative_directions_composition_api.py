"""POST /businesses/{id}/creative-directions with P2.2 spec fields.

HTTP layer through TestClient. The Higgsfield REST client is the real
HiggsfieldApiClient over httpx.MockTransport (no network, no real
Higgsfield call, no spend anywhere in this module)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield.api_client import HiggsfieldApiClient
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.db.models.business import Business
from app.db.models.business_asset import BusinessAsset
from app.db.models.tenant import Tenant
from app.dependencies import get_creative_director, get_rate_limiter, get_session
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BusinessStatus, BusinessVertical
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter

_ORIGIN = "http://localhost:5173"
SOUL = "higgsfield-ai/soul/reference"
PRESIGNED = "https://acct.r2.cloudflarestorage.com/biz/logo.png?X-Amz-Signature=SECRETSIG"


class _FakeStorage:
    provider_name = "r2"

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        return PRESIGNED


class _Gateway:
    def __init__(self, *, fail_with: tuple[int, str] | None = None) -> None:
        self.posts: list[dict] = []
        self._fail_with = fail_with

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append({"path": request.url.path, "body": json.loads(request.content)})
            if self._fail_with:
                status, detail = self._fail_with
                return httpx.Response(status, json={"detail": detail})
            n = len(self.posts)
            return httpx.Response(
                200,
                json={
                    "status": "queued",
                    "request_id": f"r-{n}",
                    "status_url": f"https://api.higgsfield.ai/requests/r-{n}/status",
                    "cancel_url": f"https://api.higgsfield.ai/requests/r-{n}/cancel",
                },
            )
        return httpx.Response(
            200, json={"status": "completed", "images": [{"url": "https://d3example.cloudfront.net/out.png"}]}
        )


def _director(gateway: _Gateway) -> FallbackCreativeDirector:
    http_client = httpx.Client(transport=httpx.MockTransport(gateway), base_url="https://api.higgsfield.ai")
    client = HiggsfieldApiClient(key_id="kid", key_secret="ksecret", http_client=http_client)
    primary = HiggsfieldApiCreativeDirector(client, job_type=SOUL, storage=_FakeStorage())
    return FallbackCreativeDirector(primary=primary, fallback=InternalCreativeDirector())


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


def _business(session: Session, tenant: Tenant, slug: str) -> Business:
    business = Business(
        tenant_id=tenant.id,
        name="Cositas y Puntos",
        slug=slug,
        vertical=BusinessVertical.OTHER,
        raw_description="Artesana espanola independiente.",
        status=BusinessStatus.ACTIVE,
        config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG.model_dump(mode="json"),
    )
    session.add(business)
    session.flush()
    return business


def _r2_logo(session: Session, business: Business) -> BusinessAsset:
    asset = BusinessAsset(
        tenant_id=business.tenant_id,
        business_id=business.id,
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://pub.example/logo.png",
        storage_provider="r2",
        storage_key="biz/logo.png",
    )
    session.add(asset)
    session.flush()
    return asset


@pytest.fixture()
def cositas(session: Session, tenant: Tenant) -> Business:
    return _business(session, tenant, "cositas-y-puntos")


def _post(client: TestClient, business: Business, tenant: Tenant, body: dict):
    return client.post(
        f"/businesses/{business.id}/creative-directions",
        json=body,
        headers={"X-Tenant-Id": str(tenant.id), "Origin": _ORIGIN},
    )


def test_hard_limit_only_body_is_backward_compatible_and_makes_one_submission(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    logo = _r2_logo(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    [direction] = response.json()
    spec = direction["generation_metadata"]["creative_spec"]
    assert spec["purpose"] == "hero"  # default purpose
    assert spec["references"][0]["asset_id"] == str(logo.id)
    assert len(gateway.posts) == 1
    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/reference"
    assert gateway.posts[0]["body"]["image_reference_url"] == PRESIGNED
    assert direction["credits_used"] == 2.0


def test_purpose_brand_mode_and_level_flow_through_to_the_spec_and_provenance(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _r2_logo(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(
        client,
        cositas,
        tenant,
        {"hard_limit": 2.0, "purpose": "background", "brand_mode": "new_direction", "creative_level": "cinematic"},
    )

    assert response.status_code == 201
    spec = response.json()[0]["generation_metadata"]["creative_spec"]
    assert (spec["purpose"], spec["brand_mode"], spec["creative_level"]) == ("background", "new_direction", "cinematic")
    assert spec["references"][0]["usage"] == "palette"  # logo is palette-only for a background / new direction
    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "full-width background" in prompt and "cinematic" in prompt


def test_the_api_response_never_exposes_presigned_urls_or_credentials(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _r2_logo(session, cositas)
    app.dependency_overrides[get_creative_director] = lambda: _director(_Gateway())

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    text = response.text
    assert (
        "SECRETSIG" not in text and "X-Amz" not in text and "ksecret" not in text and "r2.cloudflarestorage" not in text
    )


def test_invalid_purpose_is_rejected_before_any_provider_call(client: TestClient, tenant: Tenant, cositas: Business):
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "billboard"})

    assert response.status_code == 422
    assert gateway.posts == []


def test_reference_selection_never_crosses_tenant_or_business_boundaries(
    client: TestClient, session: Session, tenant: Tenant, other_tenant: Tenant, cositas: Business
):
    mine = _r2_logo(session, cositas)
    foreign_business = _business(session, other_tenant, "foreign-cositas")
    foreign_logo = _r2_logo(session, foreign_business)
    sibling = _business(session, tenant, "sibling")
    sibling_logo = _r2_logo(session, sibling)
    app.dependency_overrides[get_creative_director] = lambda: _director(_Gateway())

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    used = {ref["asset_id"] for ref in response.json()[0]["generation_metadata"]["creative_spec"]["references"]}
    assert used == {str(mine.id)}
    assert str(foreign_logo.id) not in response.text and str(sibling_logo.id) not in response.text

    cross_tenant = _post(client, foreign_business, tenant, {"hard_limit": 2.0})
    assert cross_tenant.status_code == 404


def test_model_unavailable_still_falls_back_to_internal_with_the_new_fields(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _r2_logo(session, cositas)
    gateway = _Gateway(fail_with=(404, "model_not_found"))
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "section"})

    assert response.status_code == 201
    [direction] = response.json()
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert direction["provider_metadata"]["fallback_reason"] == "higgsfield_model_unavailable"
    assert len(gateway.posts) == 1  # the fallback itself makes no provider call


def test_insufficient_credits_is_still_a_structured_503_with_a_single_submission(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _r2_logo(session, cositas)
    gateway = _Gateway(fail_with=(403, "not_enough_credits"))
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "higgsfield_insufficient_credits"
    assert len(gateway.posts) == 1
