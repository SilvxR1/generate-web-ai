"""A8.2.4 — persisting and exposing the normalized WebsiteCreativeDirection:

    InternalCreativeProvider -> CreativeGenerationResult.website_direction
    -> app.creative.orchestrator -> creative_generations.website_direction
    -> CreativeGenerationRead.website_direction (POST/GET creative-generations)

plus the additive migration, old rows reading back as null, versioned
validation, a provider contract violation failing the generation, providers
without a direction staying null, WebsiteDraft -> CreativeGeneration
traceability, tenant isolation, and write-once immutability. Local only —
no production database, no external provider."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.creative.internal import InternalCreativeProvider
from app.creative.orchestrator import INVALID_WEBSITE_DIRECTION_ERROR, orchestrate_generation
from app.creative.provider import CreativeGenerationResult, CreativeProvider
from app.db.models.business import Business
from app.db.models.creative_generation import CreativeGeneration
from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.website_direction import (
    UnsupportedWebsiteDirectionVersionError,
    WebsiteCreativeDirection,
    parse_website_direction,
)
from app.domain.enums import (
    BrandStrategy,
    BusinessVertical,
    CreativeGenerationStatus,
    CreativeGenerationType,
    CreativeProviderName,
)
from app.main import app
from app.publishing.drafts import create_website_draft
from app.schemas.creative import CreativeGenerationRead
from app.schemas.site_config import SiteConfigPayload

API_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = json.loads(
    (
        API_ROOT.parent.parent / "packages" / "site-config" / "fixtures" / "creative-direction.conformance.json"
    ).read_text("utf-8")
)
VALID_EVOLVE = CONFORMANCE["valid"]["evolve"]
MIGRATION_REVISION = "c4d7e2a9f1b3"
PREVIOUS_REVISION = "b1e2f9a08c3d"


def _config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Taller Martinez", slug="taller-martinez", industry=BusinessVertical.HOME_RENOVATION
        )
    )


def _generate(session: Session, tenant: Tenant, business: Business, **kwargs) -> CreativeGeneration:
    return orchestrate_generation(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        business_config=_config(),
        generation_type=CreativeGenerationType.WEBSITE,
        internal_provider=kwargs.pop("internal_provider", InternalCreativeProvider()),
        **kwargs,
    )


class _ResultProvider(CreativeProvider):
    """An internal-slot provider returning a fixed, caller-built result."""

    name = CreativeProviderName.INTERNAL
    capabilities = frozenset({CreativeGenerationType.WEBSITE})

    def __init__(self, result: CreativeGenerationResult) -> None:
        self.result = result

    def generate_website(self, brief):
        return self.result

    def generate_concept(self, brief):
        raise NotImplementedError

    def generate_image(self, brief, *, prompt_hint=None):
        raise NotImplementedError

    def generate_video(self, brief, *, prompt_hint=None):
        raise NotImplementedError

    def generate_visual_asset(self, brief, *, prompt_hint=None):
        raise NotImplementedError


# --- A / B / C: migration --------------------------------------------------


def _alembic(db_url: str, *args: str) -> None:
    # A subprocess: migrations/env.py calls logging.config.fileConfig, which
    # would otherwise disable this test process's own loggers.
    env = {**os.environ, "DATABASE_URL": db_url}
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert completed.returncode == 0, completed.stderr


def _columns(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {column["name"] for column in sa.inspect(engine).get_columns("creative_generations")}
    finally:
        engine.dispose()


def test_migration_adds_a_nullable_column_leaves_old_rows_null_and_downgrades_cleanly(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'migration.db'}"

    _alembic(db_url, "upgrade", PREVIOUS_REVISION)
    assert "website_direction" not in _columns(db_url)
    engine = sa.create_engine(db_url)
    old_id = uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO creative_generations "
                "(id, tenant_id, business_id, provider, generation_type, creative_level, status, generation_metadata) "
                "VALUES (:id, :tenant, :business, 'internal', 'website', 'basic', 'completed', :meta)"
            ),
            {"id": old_id, "tenant": uuid.uuid4().hex, "business": uuid.uuid4().hex, "meta": '{"note": "old"}'},
        )

    _alembic(db_url, "upgrade", MIGRATION_REVISION)

    columns = {c["name"]: c for c in sa.inspect(engine).get_columns("creative_generations")}
    assert columns["website_direction"]["nullable"] is True
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT website_direction, generation_metadata, status FROM creative_generations WHERE id = :id"),
            {"id": old_id},
        ).one()
    assert row.website_direction is None  # no backfill
    assert json.loads(row.generation_metadata) == {"note": "old"}  # untouched
    assert row.status == "completed"

    _alembic(db_url, "downgrade", PREVIOUS_REVISION)
    assert "website_direction" not in _columns(db_url)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM creative_generations")).scalar() == 1
    engine.dispose()


def test_migration_is_the_single_head():
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"], cwd=API_ROOT, capture_output=True, text=True, timeout=60
    )
    assert completed.stdout.split() == [MIGRATION_REVISION, "(head)"]


# --- D / E / F: internal provider -> persisted -> typed read ------------------


def test_internal_direction_is_persisted_and_read_back_with_identical_v1_meaning(
    session: Session, tenant: Tenant, business: Business
):
    generation = _generate(session, tenant, business, brand_strategy=BrandStrategy.NEW_DIRECTION)
    session.flush()
    session.expire_all()
    stored = session.get(CreativeGeneration, generation.id)

    assert stored.status is CreativeGenerationStatus.COMPLETED
    assert stored.website_direction is not None
    assert stored.website_direction["version"] == "1"
    persisted = WebsiteCreativeDirection.model_validate(stored.website_direction)
    assert persisted.strategy is BrandStrategy.NEW_DIRECTION

    read = CreativeGenerationRead.model_validate(stored)
    assert isinstance(read.website_direction, WebsiteCreativeDirection)
    assert read.website_direction == persisted
    assert read.model_dump(mode="json")["website_direction"] == stored.website_direction
    # generation_metadata keeps its own, separate responsibility.
    assert "website_direction" not in (stored.generation_metadata or {})


def test_the_api_returns_the_typed_direction_on_create_and_history(client: TestClient, tenant: Tenant):
    business = _create_business(client, tenant.id)

    created = client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website", "brand_strategy": "evolve", "creative_level": "basic"},
        headers=_headers(tenant.id),
    )

    assert created.status_code == 201, created.text
    direction = created.json()["website_direction"]
    assert direction["version"] == "1"
    assert direction["strategy"] == "evolve"
    assert WebsiteCreativeDirection.model_validate(direction)
    history = client.get(f"/businesses/{business['id']}/creative-generations", headers=_headers(tenant.id)).json()
    assert history[0]["website_direction"] == direction


# --- C (ORM): a generation without a direction reads back as null ------------


def test_an_old_generation_without_a_direction_reads_back_as_null(session: Session, tenant: Tenant, business: Business):
    old = CreativeGeneration(
        tenant_id=tenant.id,
        business_id=business.id,
        provider=CreativeProviderName.INTERNAL,
        generation_type=CreativeGenerationType.WEBSITE,
        creative_level="basic",
        status=CreativeGenerationStatus.COMPLETED,
        generation_metadata={"strategy": "deterministic_site_config"},
    )
    session.add(old)
    session.flush()

    assert CreativeGenerationRead.model_validate(old).website_direction is None


# --- G / H: invalid directions are rejected ----------------------------------


# The malformed direction is built with model_construct on purpose, so
# serializing it for re-validation warns; that is the scenario under test.
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_a_provider_contract_violation_fails_the_generation_and_stores_nothing_malformed(
    session: Session, tenant: Tenant, business: Business
):
    # model_construct bypasses validation — the only way a provider could
    # hand back a malformed typed direction.
    malformed = WebsiteCreativeDirection.model_construct(**{**VALID_EVOLVE, "family": "luxury"})
    result = CreativeGenerationResult(
        status=CreativeGenerationStatus.COMPLETED, credits_used=2.0, raw_metadata={"note": "x"}
    )
    object.__setattr__(result, "website_direction", malformed)

    generation = _generate(session, tenant, business, internal_provider=_ResultProvider(result))

    assert generation.status is CreativeGenerationStatus.FAILED
    assert generation.error == INVALID_WEBSITE_DIRECTION_ERROR
    assert generation.website_direction is None
    assert generation.credits_used == 2.0  # what was spent is never hidden
    assert CreativeGenerationRead.model_validate(generation).website_direction is None


@pytest.mark.parametrize("bad_key", ["businessName", "html", "provider", "credits"])
def test_extra_keys_are_rejected_on_read(bad_key):
    with pytest.raises(ValidationError):
        parse_website_direction({**VALID_EVOLVE, bad_key: "x"})


@pytest.mark.parametrize("bad_version", ["2", "0", 1, None])
def test_an_unknown_version_is_never_interpreted_as_v1(bad_version):
    with pytest.raises(UnsupportedWebsiteDirectionVersionError):
        parse_website_direction({**VALID_EVOLVE, "version": bad_version})


def test_a_stored_unknown_version_fails_loudly_on_read(session: Session, tenant: Tenant, business: Business):
    generation = _generate(session, tenant, business)
    session.flush()
    # Simulates a future-version row written behind this code's back.
    session.execute(
        sa.update(CreativeGeneration)
        .where(CreativeGeneration.id == generation.id)
        .values(website_direction={**VALID_EVOLVE, "version": "2"})
    )
    session.expire_all()

    with pytest.raises(ValidationError, match="Unsupported website direction version"):
        CreativeGenerationRead.model_validate(session.get(CreativeGeneration, generation.id))


# --- I: providers without a direction ----------------------------------------


def test_a_provider_without_a_direction_persists_null(session: Session, tenant: Tenant, business: Business):
    result = CreativeGenerationResult(status=CreativeGenerationStatus.COMPLETED, raw_metadata={"provider": "other"})

    generation = _generate(session, tenant, business, internal_provider=_ResultProvider(result))

    assert generation.status is CreativeGenerationStatus.COMPLETED
    assert generation.website_direction is None
    assert CreativeGenerationRead.model_validate(generation).website_direction is None


# --- J: WebsiteDraft -> CreativeGeneration -> direction ----------------------


def test_a_draft_reaches_its_direction_through_creative_generation_id(
    session: Session, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    from app.publishing.publisher import WebsiteArtifact

    monkeypatch.setattr(
        "app.publishing.drafts.build_site", lambda site_config: WebsiteArtifact(files={"index.html": b"<html></html>"})
    )
    generation = _generate(session, tenant, business, brand_strategy=BrandStrategy.EVOLVE)
    session.flush()
    site_config = SiteConfigPayload.model_validate(
        {
            "brand": {"name": "Taller Martinez"},
            "theme": {
                "colors": {
                    "primary": "#111",
                    "secondary": "#222",
                    "accent": "#333",
                    "background": "#fff",
                    "foreground": "#000",
                },
                "fonts": {"sans": "Inter"},
                "radius": {"base": "0.5rem", "lg": "1rem"},
            },
            "seo": {"title": "Taller", "description": "Taller."},
            "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {"heading": "Hola"}}]}],
        }
    )

    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=site_config,
        creative_generation_id=generation.id,
    )
    session.flush()

    assert draft.creative_generation_id == generation.id
    assert draft.creative_generation is not None
    explained = WebsiteCreativeDirection.model_validate(draft.creative_generation.website_direction)
    assert explained.strategy is BrandStrategy.EVOLVE
    # One canonical copy: the draft itself stores no second direction.
    assert "sectionOrder" not in json.dumps(draft.site_config)


# --- K: tenant isolation -----------------------------------------------------


def test_another_tenant_can_never_read_a_generations_direction(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
):
    business = _create_business(client, tenant.id)
    client.post(
        f"/businesses/{business['id']}/creative-generations",
        json={"generation_type": "website", "brand_strategy": "new_direction", "creative_level": "basic"},
        headers=_headers(tenant.id),
    )

    response = client.get(f"/businesses/{business['id']}/creative-generations", headers=_headers(other_tenant.id))

    assert response.status_code == 404
    assert "website_direction" not in response.text


# --- L: write-once -------------------------------------------------------------


def test_a_recorded_direction_can_never_be_overwritten_or_cleared(session: Session, tenant: Tenant, business: Business):
    generation = _generate(session, tenant, business, brand_strategy=BrandStrategy.PRESERVE)
    session.flush()
    recorded = dict(generation.website_direction)

    with pytest.raises(ValueError, match="immutable"):
        generation.website_direction = {**recorded, "density": "airy"}
    with pytest.raises(ValueError, match="immutable"):
        generation.website_direction = None

    generation.website_direction = recorded  # re-assigning the same value is a no-op
    assert generation.website_direction == recorded


def test_regenerating_creates_a_new_generation_and_never_touches_the_previous_direction(
    session: Session, tenant: Tenant, business: Business
):
    first = _generate(session, tenant, business, brand_strategy=BrandStrategy.EVOLVE)
    session.flush()
    first_direction = dict(first.website_direction)

    second = _generate(session, tenant, business, brand_strategy=BrandStrategy.NEW_DIRECTION)
    session.flush()
    session.expire_all()

    assert second.id != first.id
    assert session.get(CreativeGeneration, first.id).website_direction == first_direction
    assert session.get(CreativeGeneration, second.id).website_direction["strategy"] == "new_direction"


# --- API helpers ---------------------------------------------------------------


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _create_business(client: TestClient, tenant_id: uuid.UUID) -> dict:
    payload = {
        "name": "Taller Martinez",
        "slug": f"taller-martinez-{uuid.uuid4().hex[:6]}",
        "vertical": "home_renovation",
        "raw_description": "Taller de reparaciones con muchos anos de experiencia en la ciudad.",
        "status": "draft",
        "config": {
            "schema_version": 1,
            "business_profile": {"name": "Taller Martinez", "slug": "taller-martinez", "industry": "home_renovation"},
        },
    }
    response = client.post("/businesses", json=payload, headers=_headers(tenant_id))
    assert response.status_code == 201, response.text
    return response.json()


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}
