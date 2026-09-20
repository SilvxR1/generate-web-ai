"""CreativePromptComposer (P2.2) — semantic tests, no network/R2/Higgsfield/DB.

Deliberately never asserts one exact prompt string: each test checks a
semantic component (a rule the prompt must express) so wording can evolve
without rewriting the suite.
"""

import re
from uuid import uuid4

from app.creative.higgsfield.translation import to_higgsfield_prompt
from app.domain.business_config import BrandColors, BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset, build_creative_brief
from app.domain.creative.prompt_composer import (
    DEVELOP_ANGLES,
    EXPLORATION_ANGLES,
    ComposedCreativePrompt,
    compose_prompt,
)
from app.domain.creative.spec import (
    PROMPT_VERSION,
    CreativeGenerationSpec,
    ReferenceSpec,
    ReferenceUsage,
    build_generation_spec,
)
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
    CreativeLevel,
)

ANGLE = EXPLORATION_ANGLES[0]


def _logo() -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(),
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        url="https://cdn.example.com/logo.png",
    )


def _image(category: AssetCategory) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(),
        kind=AssetKind.IMAGE,
        category=category,
        origin=AssetOrigin.UPLOADED,
        url="https://cdn.example.com/photo.png",
    )


def _cositas_brief(**overrides) -> CreativeBrief:
    return build_creative_brief(business_config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG, **overrides)


def _spec(brief: CreativeBrief, assets, *, single_reference: bool = True) -> CreativeGenerationSpec:
    spec = build_generation_spec(brief, assets)
    return spec.with_used_references(spec.reference_assets[:1] if single_reference else spec.reference_assets)


def _compose(brief: CreativeBrief, assets=(), **kwargs) -> tuple[ComposedCreativePrompt, str]:
    composed = compose_prompt(brief, _spec(brief, list(assets)), angle=ANGLE, **kwargs)
    return composed, to_higgsfield_prompt(composed).lower()


def _blob(lines: list[str]) -> str:
    return " ".join(lines).lower()


def test_cositas_hero_with_logo_as_identity_never_asks_to_recreate_the_logo():
    """Regression scenario from the first real production generation: the
    logo (three overlapping circles plus the business name) was recreated
    and text was hallucinated. The composed prompt must make the reference
    guidance, not the subject."""
    brief = _cositas_brief()
    composed, text = _compose(brief, [_logo()])
    references = _blob(composed.reference_instructions)

    assert "official brand logo" in references
    assert "palette" in references and "geometric language" in references and "brand character" in references
    assert "do not reproduce" in references
    assert "place the logo" in references  # ...explicitly forbidden, not requested
    assert "recreate this logo" not in text and "reproduce this logo" not in text
    assert "create an original image" in text  # a NEW visual, not a re-rendering of the reference
    assert "do not recreate, redraw or approximate the official logo" in _blob(composed.negative_constraints)


def test_the_business_name_is_never_in_the_prompt_sent_to_the_provider():
    brief = _cositas_brief()
    composed, text = _compose(brief, [_logo()])

    assert brief.business_name.lower() not in text
    assert "cositas" not in text
    assert "do not write or reproduce the business name" in _blob(composed.negative_constraints)
    assert composed.debug["business_name_in_prompt"] is False


def test_the_business_name_is_scrubbed_from_free_text_facts_too():
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Cositas y Puntos hace amigurumis. Visita COSITAS Y PUNTOS en Instagram.",
            services=[
                ServiceOffering(id="svc-1", name="Llaveros de Cositas y Puntos", description="Llaveros de lana.")
            ],
        )
    )
    composed, text = _compose(build_creative_brief(business_config=config))

    assert "cositas" not in text
    assert "the business" in text
    assert "amigurumis" in text  # the verified fact itself survives


def test_no_generated_text_adds_explicit_anti_text_constraints():
    composed, _ = _compose(_cositas_brief(), [_logo()])
    negatives = _blob(composed.negative_constraints)

    for required in (
        "no words, letters, numbers or typography",
        "no captions, slogans, watermarks or signatures",
        "no fake logos",
        "no user-interface elements",
    ):
        assert required in negatives


def test_hero_expresses_hero_specific_composition_requirements():
    composed, _ = _compose(_cositas_brief(), [_logo()])
    composition = _blob(composed.composition_instructions)

    assert "focal" in composition
    assert "negative space" in composition
    assert "overlay" in composition  # room for the real HTML heading/CTA
    assert "cropping" in composition  # responsive crop tolerance
    assert "16:9" in _blob(composed.output_instructions)


def test_background_differs_materially_from_hero():
    hero, _ = _compose(_cositas_brief(purpose=AssetPurpose.HERO), [_logo()])
    background, _ = _compose(_cositas_brief(purpose=AssetPurpose.BACKGROUND), [_logo()])

    assert hero.composition_instructions != background.composition_instructions
    background_composition = _blob(background.composition_instructions)
    assert "no central subject" in background_composition
    assert "low visual density" in background_composition
    assert "contrast" in background_composition
    assert "no central subject" not in _blob(hero.composition_instructions)
    assert "focal subject" not in background_composition
    assert hero.positive_prompt != background.positive_prompt  # the stated role differs too


def test_every_purpose_produces_its_own_composition_rules():
    seen = set()
    for purpose in AssetPurpose:
        composed, _ = _compose(_cositas_brief(purpose=purpose), [_logo()])
        assert composed.composition_instructions
        seen.add(tuple(composed.composition_instructions))
    assert len(seen) == len(AssetPurpose)


def test_texture_forbids_logos_and_focal_subjects():
    composed, _ = _compose(_cositas_brief(purpose=AssetPurpose.TEXTURE), [_logo()])
    composition = _blob(composed.composition_instructions)

    assert "no focal subject" in composition
    assert "no recognisable objects, logos or marks" in composition
    assert "no duplicated or repeated subjects" not in _blob(composed.negative_constraints)  # patterns repeat


def test_product_purpose_keeps_the_product_the_primary_subject_and_faithful():
    product = _image(AssetCategory.PRODUCT)
    brief = _cositas_brief(purpose=AssetPurpose.PRODUCT)
    composed, _ = _compose(brief, [_logo(), product])

    assert _spec(brief, [_logo(), product]).reference_assets[0].usage is ReferenceUsage.PRODUCT
    assert "primary subject" in _blob(composed.composition_instructions)
    assert "real product" in _blob(composed.reference_instructions)
    assert "do not invent additional products" in _blob(composed.reference_instructions)


def test_brand_modes_materially_change_the_composed_direction():
    directions = {
        mode: _blob(_compose(_cositas_brief(brand_strategy=mode), [_logo()])[0].creative_interpretation)
        for mode in BrandStrategy
    }

    assert len(set(directions.values())) == 3
    assert "faithful" in directions[BrandStrategy.PRESERVE]
    assert "evolve" in directions[BrandStrategy.EVOLVE]
    assert "substantially new" in directions[BrandStrategy.NEW_DIRECTION]
    assert "do not redesign" in directions[BrandStrategy.PRESERVE]
    assert "constrain" in directions[BrandStrategy.NEW_DIRECTION]


def test_new_direction_treats_the_logo_as_palette_only_and_evolve_as_identity():
    new_direction, _ = _compose(_cositas_brief(brand_strategy=BrandStrategy.NEW_DIRECTION), [_logo()])
    evolve, _ = _compose(_cositas_brief(brand_strategy=BrandStrategy.EVOLVE), [_logo()])

    assert "only to take its colour palette" in _blob(new_direction.reference_instructions)
    assert "understand palette, geometric language" in _blob(evolve.reference_instructions)


def test_brand_palette_is_used_strictly_when_preserving_and_only_as_a_start_when_evolving():
    colors = BrandColors(primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFF", foreground="#000")

    def interpretation(mode):
        brief = _cositas_brief(brand_strategy=mode).model_copy(update={"brand_colors": colors})
        return _blob(_compose(brief, [_logo()])[0].creative_interpretation)

    assert "use the brand palette: primary #e8735a" in interpretation(BrandStrategy.PRESERVE)
    assert "start from the brand palette" in interpretation(BrandStrategy.EVOLVE)
    assert "#e8735a" not in interpretation(BrandStrategy.NEW_DIRECTION)


def test_creative_level_changes_the_stated_feel():
    feels = {
        level: _blob(_compose(_cositas_brief(creative_level=level), [_logo()])[0].creative_interpretation)
        for level in CreativeLevel
    }
    assert len(set(feels.values())) == len(CreativeLevel)


def test_missing_business_information_never_becomes_invented_claims():
    config = BusinessConfig(business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER))
    brief = build_creative_brief(business_config=config)
    composed, _ = _compose(brief)

    assert composed.verified_facts == [f"Industry: {brief.industry}."]  # nothing beyond what the brief states
    assert "no further verified business details" in composed.positive_prompt.lower()
    assert "do not invent" in composed.positive_prompt.lower()
    for invented in ("handmade", "bestselling", "award", "years of experience", "ceramic", "collection", "%"):
        assert invented not in composed.positive_prompt.lower()
    assert "no invented products, projects, people or testimonials" in _blob(composed.negative_constraints)


def test_verified_facts_and_creative_interpretation_are_kept_apart():
    brief = _cositas_brief()
    composed, _ = _compose(brief, [_logo()])

    assert any("amigurumi" in fact.lower() for fact in composed.verified_facts)
    assert not any(ANGLE in fact for fact in composed.verified_facts)
    assert any(ANGLE in line for line in composed.creative_interpretation)
    assert "creative interpretation, not business claims" in composed.positive_prompt.lower()
    assert "verified facts only" in composed.positive_prompt.lower()


def test_no_references_states_that_none_are_supplied_instead_of_describing_phantom_ones():
    composed, _ = _compose(_cositas_brief(), [])

    assert "no reference images are supplied" in _blob(composed.reference_instructions)
    assert "logo" not in _blob(composed.reference_instructions)


def test_only_references_actually_used_are_described():
    brief = _cositas_brief()
    spec = build_generation_spec(brief, [_logo(), _image(AssetCategory.GALLERY)])
    assert len(spec.reference_assets) == 2

    one = compose_prompt(brief, spec.with_used_references(spec.reference_assets[:1]), angle=ANGLE)
    two = compose_prompt(brief, spec, angle=ANGLE)

    assert len(one.reference_instructions) == 1
    assert len(two.reference_instructions) == 2
    assert "reference 2" in _blob(two.reference_instructions)


def test_real_photography_reference_is_style_not_subject():
    brief = _cositas_brief()
    spec = build_generation_spec(brief, [_image(AssetCategory.GALLERY)])
    composed = compose_prompt(brief, spec, angle=ANGLE)

    assert "only its mood, lighting and material feel" in _blob(composed.reference_instructions)
    assert "do not copy its subject" in _blob(composed.reference_instructions)


def test_continuation_keeps_the_same_world_and_describes_the_previous_image():
    brief = _cositas_brief()
    spec = build_generation_spec(brief, [], max_reference_candidates=0).with_used_references(
        [ReferenceSpec(asset_id=None, usage=ReferenceUsage.STYLE, source="previous_generation")]
    )

    composed = compose_prompt(brief, spec, angle=DEVELOP_ANGLES[0], continuation_of="Explored via a metaphor")

    assert "continue the same world" in composed.positive_prompt.lower()
    assert "previously generated image" in _blob(composed.reference_instructions)
    assert composed.debug["is_continuation"] is True
    assert brief.business_name.lower() not in to_higgsfield_prompt(composed).lower()


def test_no_develop_or_exploration_angle_asks_for_ui_or_text():
    for angle in (*EXPLORATION_ANGLES, *DEVELOP_ANGLES):
        for forbidden in ("navigation", "call-to-action", "cta", "contact", "menu", "button", "text"):
            assert not re.search(rf"\b{re.escape(forbidden)}\b", angle.lower())


def test_composition_is_deterministic_and_versioned():
    brief = _cositas_brief()
    assets = [_logo()]
    first, _ = _compose(brief, assets)
    second, _ = _compose(brief, assets)

    assert first.model_dump() == second.model_dump()
    assert first.version == PROMPT_VERSION


def test_translation_flattens_every_section_including_an_explicit_avoid_clause():
    composed, text = _compose(_cositas_brief(), [_logo()])

    for header in ("business context", "visual direction", "references:", "composition:", "output:", "avoid:"):
        assert header in text
    assert composed.negative_constraints[0].lower() in text


def test_a_typical_prompt_stays_compact():
    _, text = _compose(_cositas_brief(), [_logo()])
    assert len(text) < 3000
