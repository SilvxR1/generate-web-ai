"""CreativeGenerationSpec (P2.2, updated for P2.3) — pure domain tests, no
network, R2, Higgsfield or database.

Reference *selection* moved to app.domain.creative.reference_strategy in
P2.3 and is covered by test_creative_reference_strategy.py."""

from types import SimpleNamespace
from uuid import uuid4

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.planning import plan_generation
from app.domain.creative.spec import ReferenceSpec, ReferenceUsage, TextPolicy, build_generation_spec
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
    CreativeLevel,
)


def _config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Amigurumi hechos a mano.",
        )
    )


def _row(kind: AssetKind, category: AssetCategory, *, unavailable_reason: str | None = None):
    return SimpleNamespace(
        id=uuid4(),
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/a.png",
        storage_provider="r2",
        storage_key="biz/a.png",
        unavailable_reason=unavailable_reason,
        alt_text=None,
    )


def test_request_overrides_apply_to_the_brief_without_touching_business_config():
    config = _config()
    default_brief = build_creative_brief(business_config=config)
    assert default_brief.asset_purpose is AssetPurpose.HERO

    brief = build_creative_brief(
        business_config=config,
        purpose=AssetPurpose.BACKGROUND,
        brand_strategy=BrandStrategy.NEW_DIRECTION,
        creative_level=CreativeLevel.CINEMATIC,
    )

    assert brief.asset_purpose is AssetPurpose.BACKGROUND
    assert brief.brand_strategy is BrandStrategy.NEW_DIRECTION
    assert brief.creative_level is CreativeLevel.CINEMATIC
    assert brief.animation_level == "cinematic"
    assert config.creative.strategy is not BrandStrategy.NEW_DIRECTION  # never persisted or mutated


def test_spec_carries_the_brief_intent_and_only_the_references_it_is_given():
    brief = build_creative_brief(business_config=_config(), purpose=AssetPurpose.SECTION)
    reference = ReferenceSpec(asset_id=uuid4(), usage=ReferenceUsage.STYLE)

    assert build_generation_spec(brief).reference_assets == []
    spec = build_generation_spec(brief, [reference])

    assert (spec.purpose, spec.brand_mode) == (AssetPurpose.SECTION, brief.brand_strategy)
    assert spec.reference_assets == [reference]


def test_purpose_changes_the_requested_aspect_ratio():
    config = _config()
    ratios = {
        purpose: build_generation_spec(
            build_creative_brief(business_config=config, purpose=purpose)
        ).output.aspect_ratio
        for purpose in AssetPurpose
    }
    assert ratios[AssetPurpose.HERO] == "16:9"
    assert ratios[AssetPurpose.PRODUCT] == "1:1"
    assert len(set(ratios.values())) > 1


def test_generated_text_is_never_enabled_for_any_purpose():
    config = _config()
    for purpose in AssetPurpose:
        spec = build_generation_spec(build_creative_brief(business_config=config, purpose=purpose))
        assert spec.text_policy is TextPolicy.NO_GENERATED_TEXT


def test_spec_carries_ids_and_semantics_never_urls():
    reference = ReferenceSpec(asset_id=uuid4(), usage=ReferenceUsage.STYLE)
    spec = build_generation_spec(build_creative_brief(business_config=_config()), [reference])

    dumped = spec.model_dump_json()

    assert str(reference.asset_id) in dumped
    assert "http" not in dumped


def test_unavailable_assets_never_reach_the_brief_the_plan_or_any_reference():
    broken = _row(AssetKind.IMAGE, AssetCategory.PRODUCT, unavailable_reason="object_missing")
    healthy = _row(AssetKind.IMAGE, AssetCategory.PRODUCT)
    brief = build_creative_brief(business_config=_config(), assets=[broken, healthy], purpose=AssetPurpose.PRODUCT)

    plan = plan_generation(brief, brief.available_assets)

    assert [r.asset_id for r in plan.spec.reference_assets] == [healthy.id]
    assert broken.id not in {w.asset_id for w in plan.strategy.withheld}
    assert broken.id not in plan.strategy.authoritative_asset_ids
