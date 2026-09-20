"""CreativeGenerationSpec / reference selection (P2.2) — pure domain tests,
no network, R2, Higgsfield or database."""

from types import SimpleNamespace
from uuid import uuid4

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.spec import (
    AssetPurpose,
    ReferenceUsage,
    TextPolicy,
    build_generation_spec,
    reference_usage_for,
    select_references,
)
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
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


def _asset(
    kind: AssetKind,
    category: AssetCategory,
    *,
    origin: AssetOrigin = AssetOrigin.UPLOADED,
    storage_provider: str | None = None,
    storage_key: str | None = None,
) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(),
        kind=kind,
        category=category,
        origin=origin,
        url="https://cdn.example.com/a.png",
        storage_provider=storage_provider,
        storage_key=storage_key,
    )


def _logo() -> CreativeBriefAsset:
    return _asset(AssetKind.LOGO, AssetCategory.LOGO)


def _gallery() -> CreativeBriefAsset:
    return _asset(AssetKind.IMAGE, AssetCategory.GALLERY)


def _product() -> CreativeBriefAsset:
    return _asset(AssetKind.IMAGE, AssetCategory.PRODUCT)


def _hero_photo() -> CreativeBriefAsset:
    return _asset(AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE)


def _select(assets, purpose=AssetPurpose.HERO, mode=BrandStrategy.PRESERVE, limit=3):
    return select_references(assets, purpose=purpose, brand_mode=mode, limit=limit)


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


def test_logo_is_identity_for_a_hero_never_the_subject():
    logo = _logo()
    assert reference_usage_for(logo, AssetPurpose.HERO, BrandStrategy.PRESERVE) is ReferenceUsage.IDENTITY
    assert reference_usage_for(logo, AssetPurpose.HERO, BrandStrategy.EVOLVE) is ReferenceUsage.IDENTITY
    for purpose in AssetPurpose:
        for mode in BrandStrategy:
            assert reference_usage_for(logo, purpose, mode) not in (ReferenceUsage.SUBJECT, ReferenceUsage.PRODUCT)


def test_logo_only_contributes_palette_for_backgrounds_textures_and_new_directions():
    logo = _logo()
    assert reference_usage_for(logo, AssetPurpose.BACKGROUND, BrandStrategy.PRESERVE) is ReferenceUsage.PALETTE
    assert reference_usage_for(logo, AssetPurpose.TEXTURE, BrandStrategy.PRESERVE) is ReferenceUsage.PALETTE
    assert reference_usage_for(logo, AssetPurpose.HERO, BrandStrategy.NEW_DIRECTION) is ReferenceUsage.PALETTE


def test_hero_prefers_logo_identity_then_composition_then_style():
    logo, hero, gallery = _logo(), _hero_photo(), _gallery()

    refs = _select([gallery, hero, logo])

    assert [r.asset_id for r in refs] == [logo.id, hero.id, gallery.id]
    assert [r.usage for r in refs] == [ReferenceUsage.IDENTITY, ReferenceUsage.COMPOSITION, ReferenceUsage.STYLE]


def test_product_purpose_prefers_real_product_imagery_over_the_logo():
    logo, product, gallery = _logo(), _product(), _gallery()

    refs = _select([logo, gallery, product], purpose=AssetPurpose.PRODUCT)

    assert refs[0].asset_id == product.id
    assert refs[0].usage is ReferenceUsage.PRODUCT
    assert refs[1].asset_id == logo.id  # identity still available, but no longer first


def test_product_photo_is_only_style_when_the_purpose_is_not_product():
    assert reference_usage_for(_product(), AssetPurpose.HERO, BrandStrategy.PRESERVE) is ReferenceUsage.STYLE


def test_brand_mode_materially_changes_selection():
    logo, product, hero = _logo(), _product(), _hero_photo()
    assets = [product, hero, logo]

    preserve = _select(assets, mode=BrandStrategy.PRESERVE)
    new_direction = _select(assets, mode=BrandStrategy.NEW_DIRECTION)

    assert preserve[0].usage is ReferenceUsage.IDENTITY
    assert new_direction[0].usage is ReferenceUsage.PALETTE
    assert ReferenceUsage.IDENTITY not in [r.usage for r in new_direction]
    assert [r.usage for r in preserve] != [r.usage for r in new_direction]


def test_evolve_keeps_identity_but_differs_from_new_direction():
    refs = _select([_logo(), _gallery()], mode=BrandStrategy.EVOLVE)
    assert refs[0].usage is ReferenceUsage.IDENTITY


def test_low_quality_assets_are_excluded_but_the_logo_is_always_kept():
    low = _asset(AssetKind.IMAGE, AssetCategory.LOW_QUALITY)
    low_logo = _asset(AssetKind.LOGO, AssetCategory.LOW_QUALITY)

    refs = _select([low, low_logo])

    assert [r.asset_id for r in refs] == [low_logo.id]


def test_only_image_bearing_assets_can_be_references():
    video = _asset(AssetKind.VIDEO, AssetCategory.GALLERY)
    document = _asset(AssetKind.DOCUMENT, AssetCategory.OTHER)
    logo = _logo()

    refs = _select([video, document, logo])

    assert [r.asset_id for r in refs] == [logo.id]


def test_generated_assets_rank_below_real_business_assets():
    generated = _asset(AssetKind.IMAGE, AssetCategory.HERO_CANDIDATE, origin=AssetOrigin.GENERATED)
    real = _gallery()

    refs = _select([generated, real])

    assert refs[0].asset_id == real.id


def test_limit_caps_candidates_and_order_is_stable_for_equal_ranks():
    first, second, third = _gallery(), _gallery(), _gallery()

    refs = _select([first, second, third], limit=2)

    assert [r.asset_id for r in refs] == [first.id, second.id]  # caller order (newest first) preserved


def test_no_assets_means_no_references_rather_than_a_fabricated_one():
    assert _select([]) == []


def test_legacy_assets_without_storage_metadata_are_still_selectable():
    legacy = _asset(AssetKind.LOGO, AssetCategory.LOGO, storage_provider=None, storage_key=None)
    assert [r.asset_id for r in _select([legacy])] == [legacy.id]


def test_selection_only_ever_returns_ids_it_was_given_so_it_cannot_cross_businesses():
    mine = [_logo(), _gallery()]
    someone_elses = _logo()  # never passed in, as a repository scoped by tenant/business would guarantee

    refs = _select(mine)

    assert someone_elses.id not in {r.asset_id for r in refs}
    assert {r.asset_id for r in refs} <= {a.id for a in mine}


def test_unavailable_assets_never_reach_the_brief_or_the_spec():
    def row(unavailable_reason):
        return SimpleNamespace(
            id=uuid4(),
            kind=AssetKind.LOGO,
            category=AssetCategory.LOGO,
            origin=AssetOrigin.UPLOADED,
            storage_url="https://cdn.example.com/logo.png",
            storage_provider="r2",
            storage_key="biz/logo.png",
            unavailable_reason=unavailable_reason,
            alt_text=None,
        )

    broken, healthy = row("object_missing"), row(None)
    brief = build_creative_brief(business_config=_config(), assets=[broken, healthy])

    spec = build_generation_spec(brief, brief.available_assets)

    assert [r.asset_id for r in spec.reference_assets] == [healthy.id]


def test_purpose_changes_the_requested_aspect_ratio():
    config = _config()
    ratios = {
        purpose: build_generation_spec(
            build_creative_brief(business_config=config, purpose=purpose), []
        ).output.aspect_ratio
        for purpose in AssetPurpose
    }
    assert ratios[AssetPurpose.HERO] == "16:9"
    assert ratios[AssetPurpose.PRODUCT] == "1:1"
    assert len(set(ratios.values())) > 1


def test_generated_text_is_never_enabled_for_any_purpose():
    config = _config()
    for purpose in AssetPurpose:
        spec = build_generation_spec(build_creative_brief(business_config=config, purpose=purpose), [])
        assert spec.text_policy is TextPolicy.NO_GENERATED_TEXT


def test_spec_carries_ids_and_semantics_never_urls():
    logo = _logo()
    spec = build_generation_spec(build_creative_brief(business_config=_config()), [logo])

    dumped = spec.model_dump_json()

    assert str(logo.id) in dumped
    assert "http" not in dumped
