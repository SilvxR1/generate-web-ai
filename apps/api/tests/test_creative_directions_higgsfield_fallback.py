"""End-to-end (HTTP layer, TestClient) proof that a Higgsfield workspace
entitlement gap degrades POST .../creative-directions to
InternalCreativeDirector instead of failing the whole Generative Website
workflow — the production blocker this P2.1 continuation fixes. Every
Higgsfield backend is a fake, in-memory client (no real network/credit
spend anywhere in this module)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.higgsfield.api_client import HiggsfieldModelUnavailableError
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
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def create(
        self, job_type, *, prompt, image_references=None, aspect_ratio=None, resolution=None, wait_timeout="4m"
    ):
        raise self._exc


def _post_creative_directions(client: TestClient, business: Business, tenant: Tenant):
    return client.post(
        f"/businesses/{business.id}/creative-directions",
        json={},
        headers={"X-Tenant-Id": str(tenant.id), "Origin": _ORIGIN},
    )


def test_model_not_found_degrades_to_internal_and_the_pipeline_keeps_working(
    client: TestClient, tenant: Tenant, cositas_business: Business, cositas_logo_asset: BusinessAsset
):
    """The exact production symptom: Higgsfield returns 404 model_not_found
    on the configured model. Before this fix, this was a 503 dead end.
    After this fix, Studio's "Generate creative directions" still
    succeeds — with an honestly-labeled Internal-fallback candidate the
    user can select and carry through the rest of the workflow."""
    higgsfield = HiggsfieldApiCreativeDirector(
        _FailingClient(HiggsfieldModelUnavailableError("...", detail="model_not_found"))
    )
    app.dependency_overrides[get_creative_director] = lambda: FallbackCreativeDirector(
        primary=higgsfield, fallback=InternalCreativeDirector()
    )

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 201  # never the 503 a bare Higgsfield failure alone would produce
    [direction] = response.json()
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert direction["provider_metadata"]["fallback_reason"] == "higgsfield_model_unavailable"
    assert direction["is_recommended"] is True  # still a usable, selectable candidate


def test_missing_higgsfield_configuration_also_keeps_the_pipeline_working(
    client: TestClient, tenant: Tenant, cositas_business: Business
):
    app.dependency_overrides[get_creative_director] = lambda: FallbackCreativeDirector(
        primary=None, fallback=InternalCreativeDirector()
    )

    response = _post_creative_directions(client, cositas_business, tenant)

    assert response.status_code == 201
    [direction] = response.json()
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert direction["provider_metadata"]["fallback_reason"] == "higgsfield_not_configured"
