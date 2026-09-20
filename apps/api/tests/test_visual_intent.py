"""VisualIntent (P2.4) — what an image depicts, separate from where it is
used. Pure domain tests: no network, R2, Higgsfield or database."""

from uuid import uuid4

from app.domain.business_config import BrandColors, BrandConfig, BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.business_config.brand import BrandTypography
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.planning import plan_generation
from app.domain.creative.visual_intent import SubjectGrounding, VisualIntentKind
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
)

BRAND = BrandConfig(
    colors=BrandColors(primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFF", foreground="#111"),
    typography=BrandTypography(sans="Inter"),
    visual_style="handmade warmth",
)


def _plan(
    *,
    purpose: AssetPurpose = AssetPurpose.HERO,
    services: tuple[str, ...] = (),
    brand: BrandConfig | None = None,
    mode: BrandStrategy = BrandStrategy.PRESERVE,
    assets=(),
):
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Acme",
            slug="acme",
            industry=BusinessVertical.OTHER,
            services=[
                ServiceOffering(id=f"s-{i}", name=name, description="Descripcion.")
                for i, name in enumerate(services, start=1)
            ],
        ),
        brand=brand,
    )
    brief = build_creative_brief(business_config=config, purpose=purpose, brand_strategy=mode)
    return plan_generation(brief, list(assets))


def _asset(kind: AssetKind, category: AssetCategory, origin: AssetOrigin = AssetOrigin.UPLOADED):
    return CreativeBriefAsset(id=uuid4(), kind=kind, category=category, origin=origin, url="https://x/a.png")


def test_hero_is_a_placement_not_a_visual_subject():
    """Two HERO requests resolve to different intents depending on evidence —
    the purpose alone decides nothing about what is depicted."""
    with_subjects = _plan(services=("Llaveros de lana",))
    without = _plan()

    assert with_subjects.intent.kind is not without.intent.kind
    assert with_subjects.spec.purpose is AssetPurpose.HERO and without.spec.purpose is AssetPurpose.HERO


def test_a_verified_subject_resolves_to_a_conceptual_editorial_intent():
    intent = _plan(services=("Amigurumis artesanales", "Llaveros de lana")).intent

    assert intent.kind is VisualIntentKind.SUBJECT_EDITORIAL
    assert intent.grounding is SubjectGrounding.CONCEPTUAL  # a category-level depiction, not a real product photo
    assert intent.subject_categories == ["Amigurumis artesanales", "Llaveros de lana"]
    assert intent.reason == "verified_subject_categories_available"


def test_no_verified_subject_but_a_brand_profile_resolves_to_an_abstract_brand_intent():
    intent = _plan(brand=BRAND).intent

    assert intent.kind is VisualIntentKind.ABSTRACT_BRAND
    assert intent.grounding is SubjectGrounding.CONCEPTUAL
    assert intent.subject_categories == []


def test_no_verified_subject_and_no_brand_profile_is_a_safe_atmospheric_intent_never_a_product():
    intent = _plan().intent

    assert intent.kind is VisualIntentKind.ATMOSPHERIC
    assert intent.grounding is SubjectGrounding.CONCEPTUAL
    assert intent.subject_categories == []


def test_a_new_direction_ignores_the_existing_brand_profile():
    assert _plan(brand=BRAND, mode=BrandStrategy.NEW_DIRECTION).intent.kind is VisualIntentKind.ATMOSPHERIC


def test_background_and_texture_never_depict_a_subject_even_when_subjects_are_verified():
    for purpose in (AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE):
        with_brand = _plan(purpose=purpose, services=("Llaveros de lana",), brand=BRAND).intent
        without_brand = _plan(purpose=purpose, services=("Llaveros de lana",)).intent
        assert with_brand.kind is VisualIntentKind.ABSTRACT_BRAND
        assert without_brand.kind is VisualIntentKind.ATMOSPHERIC


def test_a_real_product_image_resolves_to_a_grounded_product_intent():
    plan = _plan(purpose=AssetPurpose.PRODUCT, assets=[_asset(AssetKind.IMAGE, AssetCategory.PRODUCT)])

    assert plan.intent.kind is VisualIntentKind.PRODUCT_GROUNDED
    assert plan.intent.grounding is SubjectGrounding.GROUNDED
    assert plan.strategy.requires_visual_reference is True  # PRODUCT still requires a real reference


def test_product_without_a_real_product_image_is_unknown_and_stays_unsatisfiable():
    plan = _plan(
        purpose=AssetPurpose.PRODUCT,
        services=("Llaveros de lana",),
        assets=[_asset(AssetKind.LOGO, AssetCategory.LOGO), _asset(AssetKind.IMAGE, AssetCategory.GALLERY)],
    )

    assert plan.intent.grounding is SubjectGrounding.UNKNOWN  # never upgraded to a conceptual product depiction
    assert plan.strategy.unsatisfiable_reason == "product_reference_missing"


def test_a_generated_product_image_is_not_evidence_of_a_real_product():
    plan = _plan(
        purpose=AssetPurpose.PRODUCT, assets=[_asset(AssetKind.IMAGE, AssetCategory.PRODUCT, AssetOrigin.GENERATED)]
    )
    assert plan.intent.grounding is SubjectGrounding.UNKNOWN


def test_the_official_logo_never_makes_an_intent_grounded():
    plan = _plan(assets=[_asset(AssetKind.LOGO, AssetCategory.LOGO)])

    assert plan.intent.grounding is not SubjectGrounding.GROUNDED
    assert plan.strategy.provider_reference_candidates == []


def test_intent_resolution_is_deterministic():
    assert _plan(services=("Llaveros de lana",)).intent == _plan(services=("Llaveros de lana",)).intent
