"""POST /businesses/{id}/creative-directions with P2.3 reference strategy and
model routing.

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
SOUL_REFERENCE = "higgsfield-ai/soul/reference"
PRESIGNED = "https://acct.r2.cloudflarestorage.com/biz/product.png?X-Amz-Signature=SECRETSIG"


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


def _primary(gateway: _Gateway) -> HiggsfieldApiCreativeDirector:
    http_client = httpx.Client(transport=httpx.MockTransport(gateway), base_url="https://api.higgsfield.ai")
    client = HiggsfieldApiClient(key_id="kid", key_secret="ksecret", http_client=http_client)
    return HiggsfieldApiCreativeDirector(client, job_type=SOUL_REFERENCE, storage=_FakeStorage())


def _director(gateway: _Gateway) -> FallbackCreativeDirector:
    return FallbackCreativeDirector(primary=_primary(gateway), fallback=InternalCreativeDirector())


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


def _asset(session: Session, business: Business, kind: AssetKind, category: AssetCategory, key: str) -> BusinessAsset:
    asset = BusinessAsset(
        tenant_id=business.tenant_id,
        business_id=business.id,
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        storage_url=f"https://pub.example/{key}",
        storage_provider="r2",
        storage_key=f"biz/{key}",
    )
    session.add(asset)
    session.flush()
    return asset


def _logo(session: Session, business: Business) -> BusinessAsset:
    return _asset(session, business, AssetKind.LOGO, AssetCategory.LOGO, "logo.jpg")


def _product(session: Session, business: Business) -> BusinessAsset:
    return _asset(session, business, AssetKind.IMAGE, AssetCategory.PRODUCT, "product.png")


@pytest.fixture()
def cositas(session: Session, tenant: Tenant) -> Business:
    return _business(session, tenant, "cositas-y-puntos")


def _post(client: TestClient, business: Business, tenant: Tenant, body: dict):
    return client.post(
        f"/businesses/{business.id}/creative-directions",
        json=body,
        headers={"X-Tenant-Id": str(tenant.id), "Origin": _ORIGIN},
    )


def test_the_original_hard_limit_only_body_no_longer_sends_the_logo_to_the_model(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    logo = _logo(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    [direction] = response.json()
    spec = direction["generation_metadata"]["creative_spec"]
    assert direction["provider_metadata"]["provider"] == "higgsfield"
    assert spec["purpose"] == "hero"  # default purpose
    assert spec["brand_source_asset_ids"] == [str(logo.id)]
    assert spec["provider_reference_asset_ids"] == []
    assert len(gateway.posts) == 1  # hard_limit=2.0: exactly one submission
    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/standard"
    assert "image_reference_url" not in gateway.posts[0]["body"]
    assert direction["credits_used"] == 2.0


def test_purpose_brand_mode_and_level_flow_through_the_spec_the_strategy_and_the_router(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
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
    assert spec["model_selection"]["requirements"]["aspect_ratio"] == "16:9"
    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "full-width background" in prompt and "cinematic" in prompt


def test_a_product_request_uses_the_real_product_image_via_soul_reference_and_r2_presigning(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    product = _product(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "product"})

    assert response.status_code == 201
    assert gateway.posts[0]["path"] == "/higgsfield-ai/soul/reference"
    assert gateway.posts[0]["body"]["image_reference_url"] == PRESIGNED
    spec = response.json()[0]["generation_metadata"]["creative_spec"]
    assert spec["provider_reference_asset_ids"] == [str(product.id)]
    assert "SECRETSIG" not in response.text and "X-Amz" not in response.text  # never persisted or exposed


def test_the_response_never_exposes_presigned_urls_or_credentials(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    _product(session, cositas)
    app.dependency_overrides[get_creative_director] = lambda: _director(_Gateway())

    text = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "product"}).text

    for forbidden in ("SECRETSIG", "X-Amz", "ksecret", "r2.cloudflarestorage"):
        assert forbidden not in text


def test_invalid_purpose_is_rejected_before_any_provider_call(client: TestClient, tenant: Tenant, cositas: Business):
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "billboard"})

    assert response.status_code == 422
    assert gateway.posts == []


def test_tenant_and_business_isolation_holds_for_brand_sources_and_provider_references(
    client: TestClient, session: Session, tenant: Tenant, other_tenant: Tenant, cositas: Business
):
    my_logo, my_product = _logo(session, cositas), _product(session, cositas)
    foreign = _business(session, other_tenant, "foreign-cositas")
    foreign_logo, foreign_product = _logo(session, foreign), _product(session, foreign)
    sibling = _business(session, tenant, "sibling")
    sibling_logo, sibling_product = _logo(session, sibling), _product(session, sibling)
    app.dependency_overrides[get_creative_director] = lambda: _director(_Gateway())

    hero = _post(client, cositas, tenant, {"hard_limit": 2.0})
    product = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "product"})

    hero_spec = hero.json()[0]["generation_metadata"]["creative_spec"]
    product_spec = product.json()[0]["generation_metadata"]["creative_spec"]
    assert hero_spec["brand_source_asset_ids"] == [str(my_logo.id)]
    assert product_spec["provider_reference_asset_ids"] == [str(my_product.id)]
    others = {str(a.id) for a in (foreign_logo, foreign_product, sibling_logo, sibling_product)}
    assert not any(other in hero.text or other in product.text for other in others)
    assert _post(client, foreign, tenant, {"hard_limit": 2.0}).status_code == 404  # cross-tenant


def test_model_unavailable_still_falls_back_to_internal_and_labels_it_honestly(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    gateway = _Gateway(fail_with=(404, "model_not_found"))
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    [direction] = response.json()
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert direction["provider_metadata"]["fallback_reason"] == "higgsfield_model_unavailable"
    assert direction["references"] == []  # an internal result is never presented as a generated image
    assert len(gateway.posts) == 1


def test_a_product_request_with_no_real_product_image_falls_back_explicitly_without_spending(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)  # the logo must not be used as a substitute
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "product"})

    assert response.status_code == 201
    [direction] = response.json()
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert direction["provider_metadata"]["fallback_reason"] == "higgsfield_no_suitable_model"
    assert direction["provider_metadata"]["fallback_detail"] == "product_reference_missing"
    assert direction["credits_used"] == 0.0
    assert gateway.posts == []


def test_without_the_fallback_wrapper_no_suitable_model_is_a_structured_422(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _primary(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0, "purpose": "product"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "higgsfield_no_suitable_model"
    assert gateway.posts == []


def test_insufficient_credits_is_still_a_structured_503_with_a_single_submission(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    gateway = _Gateway(fail_with=(403, "not_enough_credits"))
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "higgsfield_insufficient_credits"
    assert len(gateway.posts) == 1
