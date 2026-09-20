"""GenerationReferenceStrategy (P2.3) — which business assets MAY go to an
image model and which never do. Pure domain tests: no network, R2,
Higgsfield or database.

The experiments behind this: sending the complete official logo to a
reference-conditioned model made it recreate the logo (and its lettering)
twice, whatever the prompt said. An asset being available — even
authoritative — does not mean the provider should receive it."""

from uuid import uuid4

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.reference_strategy import (
    PRODUCT_REFERENCE_MISSING,
    ReferencePolicy,
    WithheldReason,
    decide_reference_strategy,
    is_authoritative_asset,
)
from app.domain.creative.spec import ReferenceUsage
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
)


def _asset(
    kind: AssetKind, category: AssetCategory, *, origin: AssetOrigin = AssetOrigin.UPLOADED
) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(), kind=kind, category=category, origin=origin, url="https://cdn.example.com/a.png"
    )


def _logo(**kw) -> CreativeBriefAsset:
    return _asset(AssetKind.LOGO, AssetCategory.LOGO, **kw)


def _photo(category: AssetCategory = AssetCategory.GALLERY, **kw) -> CreativeBriefAsset:
    return _asset(AssetKind.IMAGE, category, **kw)


def _strategy(assets, purpose=AssetPurpose.HERO, mode=BrandStrategy.PRESERVE):
    config = BusinessConfig(business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER))
    brief = build_creative_brief(business_config=config, purpose=purpose, brand_strategy=mode)
    return decide_reference_strategy(brief, assets)


def _sent(strategy) -> list:
    return [ref.asset_id for ref in strategy.provider_reference_candidates]


def _withheld_reason(strategy, asset):
    return next(item.reason for item in strategy.withheld if item.asset_id == asset.id)


def test_hero_with_a_logo_only_business_sends_no_reference_and_needs_no_reference_model():
    logo = _logo()

    strategy = _strategy([logo], AssetPurpose.HERO)

    assert _sent(strategy) == []
    assert strategy.policy is ReferencePolicy.NO_VISUAL_REFERENCE
    assert strategy.requires_visual_reference is False
    assert _withheld_reason(strategy, logo) is WithheldReason.LOGO_INFORMS_BRAND_PROFILE


def test_background_and_texture_with_a_logo_only_business_follow_the_same_principle():
    logo = _logo()
    for purpose in (AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE):
        strategy = _strategy([logo], purpose)
        assert _sent(strategy) == []
        assert strategy.requires_visual_reference is False


def test_the_logo_is_never_a_provider_reference_for_any_purpose_or_brand_mode():
    logo = _logo()
    for purpose in AssetPurpose:
        for mode in BrandStrategy:
            assert logo.id not in _sent(_strategy([logo, _photo(AssetCategory.PRODUCT)], purpose, mode))


def test_a_category_logo_image_is_treated_as_a_logo_too():
    logo_image = _asset(AssetKind.IMAGE, AssetCategory.LOGO)
    assert _sent(_strategy([logo_image], AssetPurpose.PRODUCT)) == []
    assert logo_image.id not in _sent(_strategy([logo_image, _photo(AssetCategory.PRODUCT)], AssetPurpose.PRODUCT))


def test_a_generated_asset_labelled_as_a_logo_is_not_the_official_logo():
    fake_logo = _logo(origin=AssetOrigin.GENERATED)
    assert not is_authoritative_asset(fake_logo)  # never an official brand source
    strategy = _strategy([fake_logo], AssetPurpose.HERO)
    assert _sent(strategy) == []


def test_the_logo_is_never_classified_as_subject_or_product():
    for purpose in AssetPurpose:
        strategy = _strategy([_logo(), _photo(AssetCategory.PRODUCT)], purpose)
        assert not any(
            ref.usage in (ReferenceUsage.SUBJECT, ReferenceUsage.PRODUCT) and ref.asset_kind is AssetKind.LOGO
            for ref in strategy.provider_reference_candidates
        )


def test_product_purpose_makes_a_real_product_image_a_required_product_reference():
    logo, product, gallery = _logo(), _photo(AssetCategory.PRODUCT), _photo(AssetCategory.GALLERY)

    strategy = _strategy([logo, gallery, product], AssetPurpose.PRODUCT)

    assert _sent(strategy) == [product.id]
    assert strategy.provider_reference_candidates[0].usage is ReferenceUsage.PRODUCT
    assert strategy.policy is ReferencePolicy.REQUIRED_SUBJECT_REFERENCE
    assert strategy.requires_visual_reference is True
    assert strategy.unsatisfiable_reason is None
    assert _withheld_reason(strategy, gallery) is WithheldReason.NOT_USED_FOR_PURPOSE


def test_product_purpose_without_a_real_product_image_is_unsatisfiable_never_invented():
    strategy = _strategy([_logo(), _photo(AssetCategory.GALLERY)], AssetPurpose.PRODUCT)

    assert strategy.unsatisfiable_reason == PRODUCT_REFERENCE_MISSING
    assert _sent(strategy) == []  # the logo is not a substitute for a product


def test_section_and_editorial_may_use_real_photography_as_an_optional_style_reference():
    hero_photo, gallery = _photo(AssetCategory.HERO_CANDIDATE), _photo(AssetCategory.GALLERY)
    for purpose in (AssetPurpose.SECTION, AssetPurpose.EDITORIAL):
        strategy = _strategy([_logo(), gallery, hero_photo], purpose)

        assert _sent(strategy) == [hero_photo.id, gallery.id]  # hero candidate first, then caller order
        assert all(ref.usage is ReferenceUsage.STYLE for ref in strategy.provider_reference_candidates)
        assert strategy.policy is ReferencePolicy.OPTIONAL_STYLE_REFERENCE
        assert strategy.requires_visual_reference is False


def test_a_new_direction_is_not_constrained_by_references():
    photo = _photo()

    strategy = _strategy([photo], AssetPurpose.EDITORIAL, BrandStrategy.NEW_DIRECTION)

    assert _sent(strategy) == []
    assert _withheld_reason(strategy, photo) is WithheldReason.NEW_DIRECTION_UNCONSTRAINED


def test_team_photos_and_unclassified_assets_are_never_sent_to_a_generation_model():
    team, unclassified = _photo(AssetCategory.TEAM), _photo(AssetCategory.OTHER)

    strategy = _strategy([team, unclassified], AssetPurpose.SECTION)

    assert _sent(strategy) == []
    assert _withheld_reason(strategy, team) is WithheldReason.PEOPLE_LIKENESS
    assert _withheld_reason(strategy, unclassified) is WithheldReason.UNCLASSIFIED


def test_non_image_assets_can_never_become_visual_references():
    video, document = _asset(AssetKind.VIDEO, AssetCategory.PRODUCT), _asset(AssetKind.DOCUMENT, AssetCategory.PRODUCT)

    for purpose in AssetPurpose:
        strategy = _strategy([video, document], purpose)
        assert _sent(strategy) == []
    product = _strategy([video, document], AssetPurpose.PRODUCT)
    assert _withheld_reason(product, video) is WithheldReason.NOT_AN_IMAGE
    assert product.unsatisfiable_reason == PRODUCT_REFERENCE_MISSING


def test_low_quality_and_previously_generated_assets_are_never_sent():
    low = _photo(AssetCategory.LOW_QUALITY)
    generated = _photo(AssetCategory.PRODUCT, origin=AssetOrigin.GENERATED)

    strategy = _strategy([low, generated], AssetPurpose.PRODUCT)

    assert _sent(strategy) == []
    assert _withheld_reason(strategy, low) is WithheldReason.LOW_QUALITY
    assert _withheld_reason(strategy, generated) is WithheldReason.GENERATED_ASSET


def test_unavailable_assets_stay_excluded_because_they_never_reach_the_strategy():
    from types import SimpleNamespace

    def row(unavailable_reason):
        return SimpleNamespace(
            id=uuid4(),
            kind=AssetKind.IMAGE,
            category=AssetCategory.PRODUCT,
            origin=AssetOrigin.UPLOADED,
            storage_url="https://cdn.example.com/p.png",
            storage_provider=None,
            storage_key=None,
            unavailable_reason=unavailable_reason,
            alt_text=None,
        )

    broken, healthy = row("object_missing"), row(None)
    config = BusinessConfig(business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER))
    brief = build_creative_brief(business_config=config, assets=[broken, healthy], purpose=AssetPurpose.PRODUCT)

    strategy = decide_reference_strategy(brief, brief.available_assets)

    assert _sent(strategy) == [healthy.id]
    assert broken.id not in {item.asset_id for item in strategy.withheld}


def test_authoritative_means_real_and_unfalsified_not_always_sent():
    logo, product = _logo(), _photo(AssetCategory.PRODUCT)
    generated, low = _photo(origin=AssetOrigin.GENERATED), _photo(AssetCategory.LOW_QUALITY)

    strategy = _strategy([logo, product, generated, low], AssetPurpose.HERO)

    assert set(strategy.authoritative_asset_ids) == {logo.id, product.id}
    assert _sent(strategy) == []  # authoritative assets are still not sent for a hero


def test_the_strategy_only_ever_reports_assets_it_was_given_so_it_cannot_cross_businesses():
    mine = [_logo(), _photo(AssetCategory.PRODUCT)]
    someone_elses = _photo(AssetCategory.PRODUCT)  # never passed in, as a scoped repository guarantees

    strategy = _strategy(mine, AssetPurpose.PRODUCT)

    everything = {*_sent(strategy), *strategy.authoritative_asset_ids, *(w.asset_id for w in strategy.withheld)}
    assert someone_elses.id not in everything
    assert everything <= {asset.id for asset in mine}


def test_strategy_is_deterministic():
    assets = [_logo(), _photo(AssetCategory.PRODUCT), _photo()]
    assert _strategy(assets, AssetPurpose.PRODUCT) == _strategy(assets, AssetPurpose.PRODUCT)
