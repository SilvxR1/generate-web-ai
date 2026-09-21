"""BrandVisualProfile (P2.3) — identity as text, built only from what can be
known reliably. Pure domain tests: no network, R2, Higgsfield or database."""

from uuid import uuid4

from app.creative.higgsfield.translation import to_higgsfield_prompt
from app.domain.business_config import BrandColors, BrandConfig, BusinessConfig, BusinessProfile
from app.domain.business_config.brand import BrandTypography
from app.domain.creative.brand_intelligence import (
    BrandAssetMeasurement,
    MeasuredColor,
    MeasurementStatus,
    PaletteMeasurement,
)
from app.domain.creative.brand_profile import (
    BRAND_PROFILE_VERSION,
    SOURCE_BRAND_COLORS,
    SOURCE_BRAND_STYLE,
    SOURCE_BRAND_TYPOGRAPHY,
    SOURCE_LOGO_PALETTE,
    SOURCE_OFFICIAL_LOGO,
    PaletteSource,
    PaletteStatus,
    build_brand_visual_profile,
    is_official_logo,
)
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.planning import plan_generation
from app.domain.creative.prompt_composer import compose_prompt
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    AssetPurpose,
    BrandStrategy,
    BusinessVertical,
)

COLORS = BrandColors(
    primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFFFFF", foreground="#111111"
)


def _brand(**overrides) -> BrandConfig:
    fields = {"colors": COLORS, "typography": BrandTypography(sans="Inter")}
    fields.update(overrides)
    return BrandConfig(**fields)


def _config(brand: BrandConfig | None = None) -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Cositas y Puntos",
            slug="cositas-y-puntos",
            industry=BusinessVertical.OTHER,
            description="Amigurumi hechos a mano.",
        ),
        brand=brand,
    )


def _logo(origin: AssetOrigin = AssetOrigin.UPLOADED) -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(), kind=AssetKind.LOGO, category=AssetCategory.LOGO, origin=origin, url="https://x/logo.jpg"
    )


def test_a_logo_only_business_gets_source_ids_but_no_invented_visual_information():
    logo = _logo()
    brief = build_creative_brief(business_config=_config())

    profile = build_brand_visual_profile(brief, [logo])

    assert profile.source_asset_ids == [logo.id]
    assert profile.has_official_logo is True
    assert profile.sources == [SOURCE_OFFICIAL_LOGO]
    assert profile.palette == [] and profile.geometry == [] and profile.mood == []  # nothing reliable to say
    assert profile.visual_style is None
    assert profile.semantic_analysis == "not_performed"  # never claims image understanding
    assert profile.version == BRAND_PROFILE_VERSION


def test_palette_and_style_come_from_structured_brand_configuration():
    brand = _brand(visual_style="handmade warmth")
    brief = build_creative_brief(business_config=_config(brand))

    profile = build_brand_visual_profile(brief, [_logo()])

    assert [(c.role, c.value) for c in profile.palette] == [
        ("primary", "#E8735A"),
        ("secondary", "#C9A24A"),
        ("accent", "#7A1F3D"),
    ]
    assert all(c.source is PaletteSource.BRAND_CONFIG for c in profile.palette)
    assert profile.visual_style == "handmade warmth"
    assert set(profile.sources) == {
        SOURCE_BRAND_COLORS,
        SOURCE_OFFICIAL_LOGO,
        SOURCE_BRAND_STYLE,
        SOURCE_BRAND_TYPOGRAPHY,
    }


def test_typography_is_a_hint_for_the_website_layer_only():
    brand = _brand(typography=BrandTypography(sans="Inter", display="Fraunces"))
    profile = build_brand_visual_profile(build_creative_brief(business_config=_config(brand)), [])

    assert profile.typography_hints == ["display: Fraunces", "body: Inter"]
    assert SOURCE_BRAND_TYPOGRAPHY in profile.sources


def test_a_generated_asset_is_never_the_official_logo():
    assert is_official_logo(_logo()) is True
    assert is_official_logo(_logo(AssetOrigin.GENERATED)) is False
    profile = build_brand_visual_profile(
        build_creative_brief(business_config=_config()), [_logo(AssetOrigin.GENERATED)]
    )
    assert profile.has_official_logo is False and profile.source_asset_ids == []


def _measurement(asset_id, *hexes: str) -> BrandAssetMeasurement:
    return BrandAssetMeasurement(
        asset_id=asset_id,
        status=MeasurementStatus.MEASURED,
        palette=PaletteMeasurement(
            colors=tuple(
                MeasuredColor(
                    hex=value,
                    role="dominant" if index == 0 else "supporting",
                    foreground_share=0.3,
                    luminance=0.3,
                    tone="mid",
                    saturation_band="moderate",
                )
                for index, value in enumerate(hexes)
            )
        ),
    )


def test_explicit_configured_colors_outrank_measured_colors():
    logo = _logo()
    brief = build_creative_brief(business_config=_config(_brand())).model_copy(
        update={"brand_measurements": [_measurement(logo.id, "#F08678", "#C8894E")]}
    )

    profile = build_brand_visual_profile(brief, [logo])

    # Configured values win outright; measured colors are never mixed in.
    assert profile.palette_status is PaletteStatus.CONFIGURED
    assert all(c.source is PaletteSource.BRAND_CONFIG for c in profile.palette)
    assert SOURCE_LOGO_PALETTE not in profile.sources and profile.measured_asset_ids == []


def test_measured_logo_colors_become_the_palette_only_when_nothing_is_configured():
    logo = _logo()
    brief = build_creative_brief(business_config=_config()).model_copy(
        update={"brand_measurements": [_measurement(logo.id, "#F08678", "#C8894E", "#f08678")]}
    )

    profile = build_brand_visual_profile(brief, [logo])

    assert profile.palette_status is PaletteStatus.MEASURED
    assert [c.value for c in profile.palette] == ["#F08678", "#C8894E"]  # duplicate hex skipped
    assert [c.role for c in profile.palette] == ["dominant", "supporting"]  # dominance, never a design role
    assert all(c.source is PaletteSource.ASSET_EXTRACTION and c.source_asset_id == logo.id for c in profile.palette)
    assert SOURCE_LOGO_PALETTE in profile.sources
    assert profile.measured_asset_ids == [logo.id] and profile.semantic_analysis == "not_performed"


def test_a_measurement_of_an_asset_that_is_not_the_official_logo_is_ignored():
    logo = _logo()
    stale = _measurement(uuid4(), "#123456")
    brief = build_creative_brief(business_config=_config()).model_copy(update={"brand_measurements": [stale]})

    profile = build_brand_visual_profile(brief, [logo])

    assert profile.palette == [] and profile.palette_status is PaletteStatus.NOT_PERFORMED


def test_the_profile_carries_no_urls_or_business_name():
    profile = build_brand_visual_profile(build_creative_brief(business_config=_config(_brand())), [_logo()])
    dumped = profile.model_dump_json()
    assert "http" not in dumped and "Cositas" not in dumped


def _prompt(brand: BrandConfig | None, mode: BrandStrategy) -> str:
    brief = build_creative_brief(business_config=_config(brand), purpose=AssetPurpose.HERO, brand_strategy=mode)
    plan = plan_generation(brief, [_logo()])
    return to_higgsfield_prompt(compose_prompt(plan.contract)).lower()


def test_the_prompt_conveys_brand_identity_as_text_without_the_logo_or_the_name():
    brand = _brand(visual_style="handmade warmth")

    text = _prompt(brand, BrandStrategy.PRESERVE)

    assert "use exactly this colour palette: primary #e8735a, secondary #c9a24a, accent #7a1f3d" in text
    assert "use exactly this visual style: handmade warmth" in text
    assert "cositas" not in text  # the name is never injected to communicate identity
    assert "the reference image" not in text  # no logo is sent, so none is described


def test_brand_mode_controls_how_much_the_profile_constrains_the_prompt():
    brand = _brand(visual_style="handmade warmth")

    assert "use exactly this colour palette" in _prompt(brand, BrandStrategy.PRESERVE)
    assert "start from this colour palette" in _prompt(brand, BrandStrategy.EVOLVE)
    new_direction = _prompt(brand, BrandStrategy.NEW_DIRECTION)
    assert "#e8735a" not in new_direction and "handmade warmth" not in new_direction


def test_missing_brand_information_adds_no_brand_direction_and_nothing_is_assumed():
    text = _prompt(None, BrandStrategy.PRESERVE)

    assert "brand direction" not in text  # nothing configured, so nothing is stated (the rationale is provenance)
    assert "palette" not in text  # no colour is invented and none is derived from a logo
