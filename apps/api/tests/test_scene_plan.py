"""VisualScenePlan (P2.5) — how a subject is depicted. Pure domain tests: no
network, R2, Higgsfield or database."""

import re
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.business_config import BrandColors, BrandConfig, BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.business_config.brand import BrandTypography
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.planning import GenerationPlan, plan_generation
from app.domain.creative.prompt_composer import compose_prompt
from app.domain.creative.scene_plan import SCENE_VARIANTS, SubjectSide, VisualScenePlan
from app.domain.creative.visual_intent import VisualIntentKind
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
    CreativeLevel,
)

BRAND = BrandConfig(
    colors=BrandColors(primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFF", foreground="#111"),
    typography=BrandTypography(sans="Inter"),
    visual_style="handmade warmth",
)


def _plan(
    *,
    purpose: AssetPurpose = AssetPurpose.HERO,
    services: tuple[str, ...] = ("Llaveros de lana",),
    brand: BrandConfig | None = None,
    mode: BrandStrategy = BrandStrategy.PRESERVE,
    level: CreativeLevel = CreativeLevel.PROFESSIONAL,
) -> GenerationPlan:
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
    brief = build_creative_brief(business_config=config, purpose=purpose, brand_strategy=mode, creative_level=level)
    return plan_generation(brief, [])


def _scene_text(scene: VisualScenePlan) -> str:
    values = scene.model_dump(mode="json", exclude={"forbidden_elements"}).values()
    return " ".join(value for value in values if isinstance(value, str))


def test_a_scene_plan_is_distinct_from_the_asset_purpose():
    plan = _plan()

    assert not hasattr(plan.scenes[0], "purpose")
    assert plan.spec.purpose is AssetPurpose.HERO  # placement is an input to composition, not the scene itself
    assert _plan(purpose=AssetPurpose.BACKGROUND).scenes[0] != plan.scenes[0]


def test_hero_maps_to_composition_never_to_website_prose():
    scene = _plan().scenes[0]
    described = _scene_text(scene).lower()

    assert scene.subject_side is SubjectSide.RIGHT
    assert "right half" in scene.placement.lower() and "left" in scene.negative_space.lower()
    assert "tolerates cropping" in scene.safe_area.lower()
    for word in ("website", "webpage", "hero", "page", "browser", "ecommerce", "layout"):
        assert word not in described


def test_hero_gets_a_wide_aspect_ratio_and_intentional_negative_space():
    scene = _plan().scenes[0]

    assert scene.aspect_ratio == "16:9"
    assert "negative space" in scene.negative_space.lower() and "uncluttered" in scene.negative_space.lower()


def test_scenes_avoid_collage_and_grid_composition_by_default_for_every_purpose():
    for purpose in AssetPurpose:
        scene = _plan(purpose=purpose).scenes[0]
        assert "collage" in scene.forbidden_elements and "grid" in scene.forbidden_elements
        assert "multi-panel layout" in scene.forbidden_elements
    assert "not a collage" in _plan().scenes[0].composition.lower()


def test_scene_elements_that_invite_text_or_interfaces_are_forbidden():
    forbidden = _plan().scenes[0].forbidden_elements

    for invites_text_or_ui in ("packaging", "shelves or storefront", "product display"):
        assert invites_text_or_ui in forbidden


def test_text_and_interface_policy_reach_the_prompt_alongside_the_scene_constraints():
    plan = _plan()
    composed = compose_prompt(plan.contract)
    constraints = " ".join(composed.constraints).lower()

    assert plan.spec.text_policy.value == "no_generated_text" and "text, lettering, pseudo-text" in constraints
    assert plan.spec.interface_policy.value == "no_interface_depiction" and "interface elements, browser" in constraints
    assert "collage, grid" in constraints


def test_a_conceptual_scene_uses_generic_materials_and_never_finished_products():
    scene = _plan().scenes[0]

    assert "no identifiable finished products" in scene.subject_treatment.lower()
    assert scene.requires_fidelity is False and scene.grounding.value == "conceptual"


def test_a_single_verified_category_without_a_family_is_depicted_as_one_simple_arrangement():
    scene = _plan(services=("Tartas de pañales",)).scenes[0]

    assert scene.medium == "Editorial photograph"  # studio photography is not hard-coded for every subject
    assert scene.primary_subject == "Tartas de pañales"
    assert "one simple arrangement" in scene.subject_treatment.lower()


def test_abstract_and_atmospheric_scenes_have_no_literal_subject():
    atmospheric = _plan(services=()).scenes[0]
    abstract = _plan(services=(), brand=BRAND).scenes[0]

    for scene in (atmospheric, abstract):
        assert scene.primary_subject is None
        assert "no literal" in scene.subject_treatment.lower()
    assert "abstract" in abstract.medium.lower() and "atmospheric" in atmospheric.medium.lower()


def test_background_and_texture_scenes_have_no_dominant_subject_side():
    for purpose in (AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE):
        scene = _plan(purpose=purpose).scenes[0]
        assert scene.subject_side is SubjectSide.NONE and "no dominant subject" in scene.placement.lower()


def test_each_purpose_gets_its_own_aspect_ratio_and_composition():
    purposes = [purpose for purpose in AssetPurpose if purpose is not AssetPurpose.PRODUCT]
    scenes = {purpose: _plan(purpose=purpose).scenes[0] for purpose in purposes}

    assert scenes[AssetPurpose.HERO].aspect_ratio == "16:9"
    assert scenes[AssetPurpose.SECTION].aspect_ratio == "4:3"
    assert scenes[AssetPurpose.EDITORIAL].aspect_ratio == "3:2"
    assert scenes[AssetPurpose.TEXTURE].aspect_ratio == "1:1"
    assert len({scene.composition for scene in scenes.values()}) == len(scenes)


def test_creative_level_changes_the_lighting():
    lighting = {level: _plan(level=level).scenes[0].lighting for level in CreativeLevel}

    assert "dramatic" in lighting[CreativeLevel.CINEMATIC].lower()
    assert lighting[CreativeLevel.PROFESSIONAL] == lighting[CreativeLevel.BASIC]
    assert len(set(lighting.values())) == 3


def test_brand_guidance_only_states_configured_information_and_respects_brand_mode():
    preserve = _plan(brand=BRAND, mode=BrandStrategy.PRESERVE).scenes[0].brand_guidance or ""
    evolve = _plan(brand=BRAND, mode=BrandStrategy.EVOLVE).scenes[0].brand_guidance or ""

    assert "use exactly this colour palette: primary #E8735A" in preserve and "handmade warmth" in preserve
    assert "start from this colour palette" in evolve
    assert _plan(brand=BRAND, mode=BrandStrategy.NEW_DIRECTION).scenes[0].brand_guidance is None
    assert _plan().scenes[0].brand_guidance is None  # nothing configured, nothing stated, nothing inferred


def test_three_deterministic_variants_mirror_the_subject_side_and_change_the_framing():
    plan = _plan()

    assert len(plan.scenes) == SCENE_VARIANTS == 3
    assert [scene.subject_side for scene in plan.scenes] == [SubjectSide.RIGHT, SubjectSide.LEFT, SubjectSide.RIGHT]
    assert len({scene.framing for scene in plan.scenes}) == 3
    assert len({scene.primary_subject for scene in plan.scenes}) == 1
    assert plan.scenes == _plan().scenes  # deterministic


def test_a_grounded_product_scene_requires_fidelity():
    config = BusinessConfig(business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER))
    product = CreativeBriefAsset(
        id=uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.PRODUCT,
        origin=AssetOrigin.UPLOADED,
        url="https://x/p.png",
    )
    plan = plan_generation(build_creative_brief(business_config=config, purpose=AssetPurpose.PRODUCT), [product])

    assert plan.intent.kind is VisualIntentKind.PRODUCT_GROUNDED
    assert plan.scenes[0].requires_fidelity is True and plan.scenes[0].grounding.value == "grounded"
    assert plan.scenes[0].aspect_ratio == "1:1"


def test_the_scene_plan_is_immutable():
    scene = _plan().scenes[0]
    with pytest.raises(ValidationError):
        scene.medium = "something else"  # type: ignore[misc]


def test_no_scene_field_names_a_web_or_interface_concept_for_any_purpose_intent_or_level():
    web = re.compile(r"\b(website|webpage|browser|screens?|interface|navigation|buttons?|menus?|ecommerce|ui)\b", re.I)
    for purpose in (AssetPurpose.HERO, AssetPurpose.SECTION, AssetPurpose.BACKGROUND, AssetPurpose.EDITORIAL):
        for services in ((), ("Llaveros de lana",), ("Tartas de pañales",)):
            for brand in (None, BRAND):
                for level in CreativeLevel:
                    for scene in _plan(purpose=purpose, services=services, brand=brand, level=level).scenes:
                        assert not web.search(_scene_text(scene))
