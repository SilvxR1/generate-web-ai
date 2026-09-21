"""CreativePromptComposer (P2.5) — semantic tests over a GenerationContract.
No network, R2, Higgsfield or database.

Never asserts one exact prompt string: each test checks a rule the rendered
prompt must express, so wording can evolve without rewriting the suite."""

from uuid import uuid4

from app.creative.higgsfield.translation import to_higgsfield_prompt
from app.domain.business_config import BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.generation_contract import validate_generation_contract
from app.domain.creative.planning import GenerationPlan, plan_generation
from app.domain.creative.prompt_composer import DEVELOP_ANGLES, compose_prompt
from app.domain.creative.spec import PROMPT_VERSION, ReferenceSpec, ReferenceUsage
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
    CreativeLevel,
)

SERVICES = ("Amigurumis artesanales hechos a mano", "Llaveros de lana", "Tartas de pañales", "Cestas personalizadas")
WEB_WORDS = ("website", "webpage", "web page", "browser", "ecommerce", "page layout", "user interface")


def _plan(
    *,
    purpose: AssetPurpose = AssetPurpose.HERO,
    services: tuple[str, ...] = SERVICES,
    mode: BrandStrategy = BrandStrategy.PRESERVE,
    level: CreativeLevel = CreativeLevel.PROFESSIONAL,
    assets=(),
) -> GenerationPlan:
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.ECOMMERCE,
            description="Marca artesanal con presencia en Instagram y sin página web.",
            target_customers="Visitantes que llegan desde Instagram.",
            services=[
                ServiceOffering(id=f"s-{i}", name=name, description="Descripcion.")
                for i, name in enumerate(services, start=1)
            ],
        )
    )
    brief = build_creative_brief(business_config=config, purpose=purpose, brand_strategy=mode, creative_level=level)
    return plan_generation(brief, list(assets))


def _asset(kind: AssetKind, category: AssetCategory) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(), kind=kind, category=category, origin=AssetOrigin.UPLOADED, url="https://cdn.example.com/a.png"
    )


def _text(plan: GenerationPlan, variant: int = 0, **kwargs) -> str:
    return to_higgsfield_prompt(compose_prompt(plan.contract_for(variant), **kwargs)).lower()


def _positive(plan: GenerationPlan, variant: int = 0) -> str:
    """The provider prompt without its final prohibitions."""
    composed = compose_prompt(plan.contract_for(variant))
    return " ".join([*composed.scene, *composed.reference_instructions]).lower()


def test_the_prompt_is_rendered_from_the_scene_plan_with_concrete_visual_instructions():
    plan = _plan()
    text = _text(plan)
    scene = plan.scenes[0]

    assert scene.medium.lower() in text
    assert scene.primary_subject and scene.primary_subject.lower() in text
    for concrete in (
        "single continuous scene",
        "wide 16:9",
        "negative space",
        "medium close-up",
        "soft natural studio light",
    ):
        assert concrete in text


def test_hero_becomes_composition_and_the_provider_is_never_told_about_a_website():
    plan = _plan()
    positive = _positive(plan)

    assert plan.spec.purpose is AssetPurpose.HERO  # kept internally...
    for word in WEB_WORDS + ("hero", "website builder", "page"):
        assert word not in positive  # ...never explained to the provider
    assert "subject concentrated toward the right half" in positive
    assert "uncluttered negative space on the left" in positive
    assert "away from the frame edges" in positive  # crop safety, purely visual


def test_hero_keeps_one_scene_and_forbids_grids_and_collages_in_the_scene_itself():
    plan = _plan()
    text = _text(plan)

    assert "not a collage" in text
    for forbidden in ("collage", "grid", "multi-panel layout", "packaging", "shelves or storefront"):
        assert forbidden in plan.scenes[0].forbidden_elements
    assert "no collage, grid, multi-panel layout" in text


def test_text_and_interface_constraints_are_short_final_sentences_rendered_once():
    composed = compose_prompt(_plan().contract)
    constraints = " ".join(composed.constraints).lower()

    for item in ("text", "lettering", "pseudo-text", "signs", "labels", "logos", "watermarks", "signatures"):
        assert item in constraints
    for item in ("interface elements", "browser", "navigation", "buttons", "cards", "screens", "webpage", "mockup"):
        assert item in constraints
    assert len(composed.constraints) == 3  # text, interface, scene — no duplicated instruction blocks
    assert "no text" in " ".join(composed.negative_constraints).lower()  # same rules for negative-prompt providers


def test_the_constraints_come_after_the_scene_and_stay_out_of_the_visual_description():
    plan = _plan()
    text = _text(plan)
    scene_part, _, constraints_part = text.rpartition("\nno ")

    assert "lettering" not in scene_part and "webpage" not in scene_part
    assert "no text" in ("no " + constraints_part)[:20] or "text" in constraints_part


def test_background_and_hero_are_composed_differently():
    hero, background = _plan(), _plan(purpose=AssetPurpose.BACKGROUND)

    assert _positive(hero) != _positive(background)
    assert "no dominant subject" in _positive(background)
    assert "subject concentrated" in _positive(hero) and "subject concentrated" not in _positive(background)


def test_every_purpose_renders_a_distinct_valid_scene_with_its_own_aspect_ratio():
    seen = set()
    for purpose in AssetPurpose:
        assets = [_asset(AssetKind.IMAGE, AssetCategory.PRODUCT)] if purpose is AssetPurpose.PRODUCT else []
        plan = _plan(purpose=purpose, assets=assets)
        composed = compose_prompt(plan.contract)
        assert composed.scene and not validate_generation_contract(plan.contract)
        seen.add((tuple(composed.scene), plan.spec.output.aspect_ratio))
    assert len(seen) == len(AssetPurpose)


def test_no_references_are_described_when_none_are_sent():
    text = _text(_plan())
    assert "reference image" not in text


def test_a_real_product_reference_is_described_as_the_faithful_subject():
    product = _asset(AssetKind.IMAGE, AssetCategory.PRODUCT)
    plan = _plan(purpose=AssetPurpose.PRODUCT, assets=[product])
    contract = plan.contract_for(0, plan.spec.reference_assets)

    composed = compose_prompt(contract)

    reference = " ".join(composed.reference_instructions).lower()
    assert "real product" in reference and "faithful" in reference and "add nothing invented" in reference
    assert "clean product photograph" in " ".join(composed.scene).lower()


def test_a_brand_mark_reference_is_rendered_defensively_and_rejected_by_the_contract():
    plan = _plan()
    contract = plan.contract.with_provider_references([ReferenceSpec(asset_id=uuid4(), usage=ReferenceUsage.IDENTITY)])

    composed = compose_prompt(contract)

    assert "do not reproduce it" in " ".join(composed.reference_instructions).lower()
    assert "brand_mark_as_provider_reference" in {issue.code for issue in validate_generation_contract(contract)}


def test_business_name_and_raw_business_text_never_reach_the_prompt():
    text = _text(_plan())

    for leaked in ("cositas", "puntos", "instagram", "página web", "presencia", "visitantes", "marca artesanal"):
        assert leaked not in text


def test_a_continuation_keeps_the_same_world_and_a_variation_is_appended():
    plan = _plan()

    composed = compose_prompt(plan.contract, variation=DEVELOP_ANGLES[1], continuation_of="the first exploration")
    text = " ".join(composed.scene).lower()

    assert text.startswith("continue the same visual world as the reference image")
    assert "close, tactile detail" in text
    assert composed.debug["is_continuation"] is True


def test_the_three_exploration_variants_are_distinct_deterministic_scenes_of_one_subject():
    plan = _plan()

    prompts = [_text(plan, variant) for variant in range(3)]

    assert len(set(prompts)) == 3
    assert len({scene.primary_subject for scene in plan.scenes}) == 1  # same subject, different composition
    assert [scene.subject_side.value for scene in plan.scenes] == ["right", "left", "right"]
    assert prompts == [_text(plan, variant) for variant in range(3)]  # deterministic


def test_the_composed_prompt_is_versioned_and_records_no_business_text_in_debug():
    composed = compose_prompt(_plan().contract)

    assert composed.version == PROMPT_VERSION == "p2.6-v1"
    assert composed.debug["business_name_in_prompt"] is False
    assert composed.debug["raw_business_description_in_prompt"] is False
    assert composed.debug["visual_intent"] == "subject_editorial"


def test_the_provider_prompt_is_flat_visual_text_without_internal_section_headers_and_is_compact():
    text = to_higgsfield_prompt(compose_prompt(_plan().contract))

    for header in ("OUTPUT CONTRACT", "PLACEMENT", "VISUAL INTENT", "SUBJECT TRUTH", "INTERFACE POLICY", "AVOID:"):
        assert header not in text
    assert len(text) < 1800  # P2.4's equivalent prompt was ≈3,470 characters
