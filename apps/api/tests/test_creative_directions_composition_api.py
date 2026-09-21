"""POST /businesses/{id}/creative-directions with P2.3 reference strategy and
model routing.

HTTP layer through TestClient. The Higgsfield REST client is the real
HiggsfieldApiClient over httpx.MockTransport (no network, no real
Higgsfield call, no spend anywhere in this module)."""

import json
import re
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield.api_client import HiggsfieldApiClient
from app.creative.higgsfield.director import HiggsfieldApiCreativeDirector
from app.db.models.business import Business
from app.db.models.business_asset import BusinessAsset
from app.db.models.tenant import Tenant
from app.dependencies import get_creative_director, get_rate_limiter, get_session, get_storage_provider
from app.domain.business_config.brand import BrandColors, BrandConfig, BrandTypography
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BusinessStatus, BusinessVertical
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter
from app.storage.local import LocalStorageProvider

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


def test_the_response_records_visual_intent_grounding_and_context_decisions_without_business_text(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business
):
    _logo(session, cositas)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    spec = response.json()[0]["generation_metadata"]["creative_spec"]
    assert spec["visual_intent"] in {"atmospheric", "abstract_brand", "subject_editorial"}
    assert spec["subject_grounding"] == "conceptual"
    assert spec["interface_policy"] == "no_interface_depiction"
    excluded_fields = {item["field"] for item in spec["creative_context"]["excluded"]}
    assert {"business_name", "description"} <= excluded_fields
    assert spec["visual_subject_source"] in {"none", "material_family_from_verified_labels", "single_verified_category"}
    assert spec["scene_plan"]["aspect_ratio"] == "16:9" and spec["scene_plan"]["subject_side"] in {"right", "none"}
    assert spec["scene_plan_version"] and spec["generation_contract_version"]
    prompt = gateway.posts[0]["body"]["prompt"].lower()
    assert "wide 16:9" in prompt and "negative space" in prompt and "no webpage" not in prompt.split("\nno ")[0]
    assert "artesana" not in prompt and "cositas" not in prompt  # neither the name nor the raw description
    for web_word in ("website", "hero", "page layout", "ecommerce"):
        assert web_word not in prompt.split("\nno ")[0]  # placement is composition, not web vocabulary


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
    assert "no dominant subject" in prompt and "dramatic" in prompt  # background composition, cinematic lighting


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


# --- P2.6: Brand Intelligence through the real route --------------------------------------------------


class _SpyLocalStorage(LocalStorageProvider):
    """The real local provider presenting as the production provider name;
    records loads and refuses to mint a presigned URL."""

    provider_name = "r2"

    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root)
        self.loads: list[str] = []

    def load(self, storage_key: str) -> bytes:
        self.loads.append(storage_key)
        return super().load(storage_key)

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        raise AssertionError("Brand Intelligence must never request a presigned URL")


def _logo_bytes() -> bytes:
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 80, 260, 240), fill=(240, 133, 122))
    draw.ellipse((220, 80, 380, 240), fill=(201, 138, 78))
    draw.ellipse((340, 80, 500, 240), fill=(120, 58, 90))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


def _unbranded(session: Session, business: Business) -> None:
    """Cositas in production has `brand: null` — nothing configured to outrank the logo."""
    business.config = {**business.config, "brand": None}
    session.flush()


def _stored_logo(session: Session, business: Business, storage: _SpyLocalStorage, *, key_owner=None) -> BusinessAsset:
    key = f"{key_owner or business.id}/logo.jpg"
    storage.save(storage_key=key, content=_logo_bytes())
    asset = BusinessAsset(
        tenant_id=business.tenant_id,
        business_id=business.id,
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        storage_url=f"https://pub.example/{key}",
        storage_provider="r2",
        storage_key=key,
    )
    session.add(asset)
    session.flush()
    return asset


@pytest.fixture()
def spy_storage(tmp_path: Path):
    storage = _SpyLocalStorage(tmp_path)
    app.dependency_overrides[get_storage_provider] = lambda: storage
    try:
        yield storage
    finally:
        app.dependency_overrides.pop(get_storage_provider, None)


def test_the_route_measures_the_official_logo_and_styles_the_scene_without_sending_it(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business, spy_storage: _SpyLocalStorage
):
    _unbranded(session, cositas)
    logo = _stored_logo(session, cositas, spy_storage)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    spec = response.json()[0]["generation_metadata"]["creative_spec"]
    profile = spec["brand_profile"]
    assert profile["palette_status"] == "measured" and len(profile["palette"]) == 3
    prompt = gateway.posts[0]["body"]["prompt"]
    assert all(color in prompt for color in profile["palette"])  # the measured colors reached the provider prompt
    assert set(gateway.posts[0]["body"]) == {"prompt", "aspect_ratio"} and "http" not in prompt
    assert spec["provider_reference_asset_ids"] == [] and spec["brand_source_asset_ids"] == [str(logo.id)]
    assert spy_storage.loads == [logo.storage_key]  # read once, through the storage abstraction
    assert len(gateway.posts) == 1
    assert "logo.jpg" not in response.text and str(cositas.id) not in json.dumps(profile)  # keys never exposed
    assert re.search(r"X-Amz|presign", response.text, re.IGNORECASE) is None


def test_a_logo_object_owned_by_another_business_is_never_read_and_generation_proceeds(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business, spy_storage: _SpyLocalStorage
):
    _unbranded(session, cositas)
    foreign_business = _business(session, tenant, "other-business")
    _stored_logo(session, cositas, spy_storage, key_owner=foreign_business.id)  # row points at a foreign object
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201 and len(gateway.posts) == 1
    profile = response.json()[0]["generation_metadata"]["creative_spec"]["brand_profile"]
    assert profile["palette_status"] == "failed" and profile["analysis_failure"] == "asset_unreadable"
    assert spy_storage.loads == []  # the foreign object was refused before any read
    assert "palette" not in gateway.posts[0]["body"]["prompt"].lower()


def test_configured_brand_colors_outrank_the_logo_and_no_bytes_are_read(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business, spy_storage: _SpyLocalStorage
):
    brand = BrandConfig(
        colors=BrandColors(
            primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFFFFF", foreground="#111111"
        ),
        typography=BrandTypography(sans="Inter"),
    )
    cositas.config = {**cositas.config, "brand": brand.model_dump(mode="json")}  # explicit, configured brand colors
    session.flush()
    _stored_logo(session, cositas, spy_storage)
    gateway = _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(gateway)

    response = _post(client, cositas, tenant, {"hard_limit": 2.0})

    assert response.status_code == 201
    profile = response.json()[0]["generation_metadata"]["creative_spec"]["brand_profile"]
    assert profile["palette_status"] == "configured" and profile["palette_source"] == "brand_config"
    assert profile["measured_palette"] == [] and spy_storage.loads == []


@pytest.mark.parametrize("requested", ["professional", "cinematic", "basic", None])
def test_the_generation_row_records_the_level_that_was_actually_requested(
    client: TestClient, session: Session, tenant: Tenant, cositas: Business, requested: str | None
):
    """Regression (found in Experiment 5): the CreativeGeneration audit row hardcoded
    creative_level=PREMIUM whatever the request said, contradicting the provenance."""
    _logo(session, cositas)
    app.dependency_overrides[get_creative_director] = lambda: _director(_Gateway())
    body: dict = {"hard_limit": 2.0}
    if requested:
        body["creative_level"] = requested

    response = _post(client, cositas, tenant, body)

    assert response.status_code == 201
    spec_level = response.json()[0]["generation_metadata"]["creative_spec"]["creative_level"]
    history = client.get(
        f"/businesses/{cositas.id}/creative-generations", headers={"X-Tenant-Id": str(tenant.id), "Origin": _ORIGIN}
    ).json()
    row_level = history[0]["creative_level"]
    assert row_level == spec_level  # audit row and provenance now agree
    if requested:
        assert row_level == requested
