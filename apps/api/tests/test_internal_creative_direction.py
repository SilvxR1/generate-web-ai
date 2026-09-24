"""A8.2.2 — the BASIC/internal provider deterministically derives a
canonical WebsiteCreativeDirection v1 (app.creative.internal_direction).

Proves the acceptance criteria end to end on representative, synthetic
businesses (never a specific real one): every output validates against the
canonical contract; the same inputs always give the same direction; EVOLVE
and NEW_DIRECTION differ materially (not only in `strategy`); PRESERVE keeps
the brand palette; no business fact, asset URL or asset id can appear; the
gallery cap stays bounded; family resolution matches website-generator's
TypeScript resolver on the shared fixture; unknown context falls back to
generic; and no network call is made."""

import itertools
import json
import socket
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.creative.internal import InternalCreativeProvider
from app.creative.internal_direction import (
    DirectionContext,
    derive_website_creative_direction,
    direction_context_from_brief,
    resolve_design_family,
)
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.brand import BrandColors, BrandConfig, BrandTypography
from app.domain.business_config.business_profile import ContactInfo, ServiceOffering
from app.domain.creative import build_creative_brief
from app.domain.creative.website_direction import GALLERY_MAX_ITEMS_MAX, GALLERY_MAX_ITEMS_MIN, WebsiteCreativeDirection
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BrandStrategy, BusinessVertical

REPO_ROOT = Path(__file__).resolve().parents[3]
FAMILY_CONFORMANCE = json.loads(
    (REPO_ROOT / "packages" / "website-generator" / "fixtures" / "design-family.conformance.json").read_text("utf-8")
)
DIRECTION_CONFORMANCE = json.loads(
    (REPO_ROOT / "packages" / "site-config" / "fixtures" / "creative-direction.conformance.json").read_text("utf-8")
)

# Distinctive, synthetic facts — the direction must never echo any of them.
FACTS = {
    "name": "Zyxwv Talleres Quimera",
    "description": "Fabricamos quimeras artesanales desde 1987 en Albacete.",
    "service": "Restauración de quimeras",
    "phone": "+34 611 222 333",
    "email": "quimera@example.com",
    "tagline": "Las mejores quimeras del mundo",
    "service_description": "Devolvemos la vida a quimeras antiguas.",
}

PRESENTATION_FIELDS = (
    "family",
    "palette",
    "typography",
    "radius",
    "density",
    "sectionOrder",
    "hero",
    "gallery",
    "surfaces",
    "cta",
)


def _asset(category: AssetCategory, *, n: int, origin: AssetOrigin = AssetOrigin.UPLOADED):
    asset_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{category}-{n}-{origin}")
    return SimpleNamespace(
        id=asset_id,
        kind=AssetKind.IMAGE,
        category=category,
        origin=origin,
        storage_url=f"https://cdn.example.test/uploads/{asset_id}.jpg",
        storage_provider=None,
        storage_key=None,
        unavailable_reason=None,
        alt_text=None,
    )


def _config(industry: BusinessVertical, *, brand: bool, visual_style: str | None = None) -> BusinessConfig:
    profile = BusinessProfile(
        name=FACTS["name"],
        slug="zyxwv-talleres-quimera",
        industry=industry,
        description=FACTS["description"],
        services=[ServiceOffering(id="quimeras", name=FACTS["service"], description=FACTS["service_description"])],
        contact=ContactInfo(phone=FACTS["phone"], email=FACTS["email"]),
    )
    fields: dict = {"business_profile": profile}
    if brand:
        fields["brand"] = BrandConfig(
            tagline=FACTS["tagline"],
            colors=BrandColors(
                primary="#123456", secondary="#654321", accent="#abcdef", background="#ffffff", foreground="#000000"
            ),
            typography=BrandTypography(sans="Inter, sans-serif"),
            visual_style=visual_style,
        )
    return BusinessConfig(**fields)


# Representative contexts: every family, with/without brand colours,
# photo-rich and photo-less.
CONTEXTS: dict[str, tuple[BusinessConfig, list]] = {
    "renovation_branded_with_projects": (
        _config(BusinessVertical.HOME_RENOVATION, brand=True),
        [_asset(AssetCategory.PROJECT, n=i) for i in range(5)],
    ),
    "clinic_unbranded_no_photos": (_config(BusinessVertical.CLINIC, brand=False), []),
    "restaurant_branded_with_hero": (
        _config(BusinessVertical.RESTAURANT, brand=True),
        [_asset(AssetCategory.HERO_CANDIDATE, n=0), _asset(AssetCategory.GALLERY, n=1)],
    ),
    "handmade_shop_many_products": (
        _config(BusinessVertical.OTHER, brand=True, visual_style="handmade, colourful"),
        [_asset(AssetCategory.GALLERY, n=i) for i in range(38)],
    ),
    "ecommerce_generic_one_photo": (
        _config(BusinessVertical.ECOMMERCE, brand=False),
        [_asset(AssetCategory.PRODUCT, n=0)],
    ),
    "other_only_generated_photos": (
        _config(BusinessVertical.OTHER, brand=False),
        [_asset(AssetCategory.GALLERY, n=i, origin=AssetOrigin.GENERATED) for i in range(4)],
    ),
}


def _direction(name: str, strategy: BrandStrategy) -> WebsiteCreativeDirection:
    config, assets = CONTEXTS[name]
    brief = build_creative_brief(business_config=config, assets=assets, brand_strategy=strategy)
    result = InternalCreativeProvider().generate_website(brief)
    assert result.website_direction is not None
    return result.website_direction


ALL_CASES = list(itertools.product(sorted(CONTEXTS), list(BrandStrategy)))


# A / H / I — every output is a valid canonical direction -------------------


@pytest.mark.parametrize(("context", "strategy"), ALL_CASES)
def test_every_internal_direction_is_a_valid_canonical_v1_direction(context, strategy):
    dumped = _direction(context, strategy).model_dump(mode="json")

    reparsed = WebsiteCreativeDirection.model_validate(dumped)

    assert reparsed.model_dump(mode="json") == dumped
    assert dumped["version"] == "1"
    assert dumped["strategy"] == strategy.value
    assert GALLERY_MAX_ITEMS_MIN <= dumped["gallery"]["maxItems"] <= GALLERY_MAX_ITEMS_MAX
    assert dumped["gallery"]["maxItems"] <= 12  # a home page, never an archive
    assert 0 < len(dumped["rationale"]) <= DIRECTION_CONFORMANCE["vocabulary"]["rationale.maxLength"]


@pytest.mark.parametrize(("context", "strategy"), ALL_CASES)
def test_every_value_is_drawn_from_the_shared_contract_vocabulary(context, strategy):
    dumped = _direction(context, strategy).model_dump(mode="json")
    vocab = DIRECTION_CONFORMANCE["vocabulary"]

    assert dumped["family"] in vocab["family"]
    assert dumped["palette"]["mode"] in vocab["palette.mode"]
    assert dumped["palette"].get("derivation", "tonal_shift") in vocab["palette.derivation"]
    assert dumped["typography"]["pairing"] in vocab["typography.pairing"]
    assert dumped["radius"] in vocab["radius"]
    assert dumped["density"] in vocab["density"]
    assert sorted(dumped["sectionOrder"]) == sorted(vocab["sectionOrder"])
    assert dumped["hero"]["layout"] in vocab["hero.layout"]
    assert dumped["gallery"]["layout"] in vocab["gallery.layout"]
    assert dumped["surfaces"]["mode"] in vocab["surfaces.mode"]
    assert dumped["cta"]["variant"] in vocab["cta.variant"]


# B — determinism ----------------------------------------------------------


@pytest.mark.parametrize(("context", "strategy"), ALL_CASES)
def test_same_inputs_and_strategy_always_give_the_identical_direction(context, strategy):
    first = _direction(context, strategy)
    second = _direction(context, strategy)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_the_direction_does_not_depend_on_asset_identity_or_order():
    config, assets = CONTEXTS["renovation_branded_with_projects"]
    reordered = list(reversed(assets))
    renamed = [
        SimpleNamespace(**{**vars(asset), "id": uuid.uuid4(), "storage_url": f"https://x.test/{i}.jpg"})
        for i, asset in enumerate(assets)
    ]

    base = _direction("renovation_branded_with_projects", BrandStrategy.NEW_DIRECTION)
    for variant in (reordered, renamed):
        brief = build_creative_brief(business_config=config, assets=variant, brand_strategy=BrandStrategy.NEW_DIRECTION)
        assert InternalCreativeProvider().generate_website(brief).website_direction == base


# C / D — EVOLVE vs NEW_DIRECTION differ materially ------------------------


@pytest.mark.parametrize("context", sorted(CONTEXTS))
def test_evolve_and_new_direction_differ_in_several_presentation_fields(context):
    evolve = _direction(context, BrandStrategy.EVOLVE).model_dump(mode="json")
    new = _direction(context, BrandStrategy.NEW_DIRECTION).model_dump(mode="json")

    differing = [field for field in PRESENTATION_FIELDS if evolve[field] != new[field]]

    assert len(differing) >= 6, differing
    assert {"family", "typography", "sectionOrder", "density"} <= set(differing)


@pytest.mark.parametrize("context", sorted(CONTEXTS))
def test_the_difference_is_never_strategy_only(context):
    evolve = _direction(context, BrandStrategy.EVOLVE).model_dump(mode="json")
    new = _direction(context, BrandStrategy.NEW_DIRECTION).model_dump(mode="json")

    without_strategy = [{k: v for k, v in d.items() if k not in ("strategy", "rationale")} for d in (evolve, new)]

    assert without_strategy[0] != without_strategy[1]


@pytest.mark.parametrize("context", sorted(CONTEXTS))
def test_preserve_and_evolve_also_differ_but_keep_the_same_family(context):
    preserve = _direction(context, BrandStrategy.PRESERVE)
    evolve = _direction(context, BrandStrategy.EVOLVE)

    assert preserve.family == evolve.family
    assert preserve.sectionOrder == evolve.sectionOrder
    assert (preserve.density, preserve.gallery) != (evolve.density, evolve.gallery)


# E / palette intent ---------------------------------------------------------


@pytest.mark.parametrize("context", sorted(CONTEXTS))
def test_preserve_always_uses_the_brand_palette(context):
    assert _direction(context, BrandStrategy.PRESERVE).palette.mode == "brand"


def test_evolve_and_new_direction_derive_from_brand_colours_only_when_they_exist():
    branded_evolve = _direction("renovation_branded_with_projects", BrandStrategy.EVOLVE).palette
    branded_new = _direction("renovation_branded_with_projects", BrandStrategy.NEW_DIRECTION).palette
    unbranded_new = _direction("clinic_unbranded_no_photos", BrandStrategy.NEW_DIRECTION).palette

    assert branded_evolve.model_dump() == {"mode": "brand_derived", "derivation": "tonal_shift"}
    assert branded_new.model_dump() == {"mode": "brand_derived", "derivation": "contrast_up"}
    assert unbranded_new.model_dump() == {"mode": "family"}


# F / G — no business facts, no asset references ---------------------------


@pytest.mark.parametrize(("context", "strategy"), ALL_CASES)
def test_no_business_fact_asset_url_or_asset_id_ever_appears(context, strategy):
    _config_unused, assets = CONTEXTS[context]
    serialized = _direction(context, strategy).model_dump_json().lower()

    for fact in FACTS.values():
        assert fact.lower() not in serialized
    for token in ("zyxwv", "quimera", "albacete", "1987", "611", "example.test", "example.com", "#123456"):
        assert token not in serialized
    for asset in assets:
        assert str(asset.id) not in serialized
        assert asset.storage_url.lower() not in serialized
    assert "http" not in serialized


def test_the_derivation_context_is_a_presentation_projection_only():
    fields = set(DirectionContext.__dataclass_fields__)

    assert fields == {
        "strategy",
        "industry",
        "visual_style",
        "has_brand_colors",
        "real_gallery_asset_count",
        "has_hero_image",
    }


# Gallery / sections -------------------------------------------------------


def test_gallery_caps_are_bounded_and_tighten_from_preserve_to_new_direction():
    caps = {s: _direction("handmade_shop_many_products", s).gallery.maxItems for s in BrandStrategy}

    assert caps == {BrandStrategy.PRESERVE: 12, BrandStrategy.EVOLVE: 9, BrandStrategy.NEW_DIRECTION: 6}


def test_new_direction_leads_with_the_story_and_photos_first_only_when_photos_exist():
    assert _direction("handmade_shop_many_products", BrandStrategy.NEW_DIRECTION).sectionOrder == [
        "about",
        "gallery",
        "services",
    ]
    assert _direction("clinic_unbranded_no_photos", BrandStrategy.NEW_DIRECTION).sectionOrder == [
        "about",
        "services",
        "gallery",
    ]


def test_generated_photos_never_count_as_a_real_gallery():
    config, assets = CONTEXTS["other_only_generated_photos"]
    brief = build_creative_brief(business_config=config, assets=assets, brand_strategy=BrandStrategy.PRESERVE)

    context = direction_context_from_brief(brief)

    assert context.real_gallery_asset_count == 0
    assert _direction("other_only_generated_photos", BrandStrategy.PRESERVE).family == "generic"


def test_a_business_without_any_photo_never_gets_a_split_hero():
    for strategy in BrandStrategy:
        assert _direction("clinic_unbranded_no_photos", strategy).hero.layout == "centered"


# J / K — family mapping ---------------------------------------------------


@pytest.mark.parametrize("case", FAMILY_CONFORMANCE["cases"], ids=lambda c: f"{c['industry']}-{c['visualStyle']}")
def test_family_resolution_matches_website_generator_on_the_shared_fixture(case):
    assert resolve_design_family(case["industry"], case["visualStyle"], case["realGalleryAssetCount"]) == case["family"]


def test_unknown_business_context_falls_back_to_generic():
    assert resolve_design_family("spaceship_dealer", None, 0) == "generic"
    assert resolve_design_family("spaceship_dealer", "handmade", 40) == "generic"
    direction = derive_website_creative_direction(
        DirectionContext(
            strategy=BrandStrategy.PRESERVE,
            industry="spaceship_dealer",
            visual_style=None,
            has_brand_colors=False,
            real_gallery_asset_count=0,
            has_hero_image=False,
        )
    )
    assert direction.family == "generic"


def test_every_family_maps_to_a_different_new_direction_family():
    for industry in ("home_renovation", "clinic", "restaurant", "ecommerce"):
        for photos in (0, 5):
            context = DirectionContext(
                strategy=BrandStrategy.NEW_DIRECTION,
                industry=industry,
                visual_style=None,
                has_brand_colors=True,
                real_gallery_asset_count=photos,
                has_hero_image=photos > 0,
            )
            current = resolve_design_family(industry, None, photos)
            assert derive_website_creative_direction(context).family != current


# L — no network / provider call ------------------------------------------


def test_generating_a_direction_makes_no_network_call(monkeypatch: pytest.MonkeyPatch):
    def _no_network(*args, **kwargs):
        raise AssertionError("InternalCreativeProvider must never open a network connection")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)

    for context, strategy in ALL_CASES:
        assert _direction(context, strategy) is not None


def test_other_result_producers_default_to_no_direction():
    from app.creative.provider import CreativeGenerationResult
    from app.domain.enums import CreativeGenerationStatus

    assert CreativeGenerationResult(status=CreativeGenerationStatus.COMPLETED).website_direction is None


def test_rationale_never_describes_a_gallery_or_brand_colours_the_business_does_not_have():
    for strategy in BrandStrategy:
        rationale = _direction("clinic_unbranded_no_photos", strategy).rationale.lower()
        assert "photo" not in rationale and "gallery" not in rationale
        assert "brand colour" not in rationale and "brand palette" not in rationale
    assert "photos" in _direction("handmade_shop_many_products", BrandStrategy.EVOLVE).rationale
