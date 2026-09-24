"""A8.2.1 — WebsiteCreativeDirection (app.domain.creative.website_direction),
the Pydantic mirror of packages/site-config's canonical TypeScript
contract. Held to the SAME packages/site-config/fixtures/
creative-direction.conformance.json the TypeScript suite asserts, so the
two validators can only change together: every valid case must parse and
dump back to the identical JSON, every invalid case must be rejected, and
the vocabulary here must equal the fixture's."""

import json
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.creative import website_direction as wd
from app.domain.creative.website_direction import WebsiteCreativeDirection
from app.domain.enums import BrandStrategy

CONFORMANCE_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "site-config"
    / "fixtures"
    / "creative-direction.conformance.json"
)
CONFORMANCE = json.loads(CONFORMANCE_PATH.read_text(encoding="utf-8"))


def _literal(alias) -> list[str]:
    return list(typing.get_args(alias))


def test_vocabulary_matches_the_shared_conformance_fixture():
    assert {
        "version": wd.WEBSITE_CREATIVE_DIRECTION_VERSION,
        "strategy": [strategy.value for strategy in BrandStrategy],
        "family": _literal(wd.WebsiteDesignFamily),
        "palette.mode": ["brand", "brand_derived", "family"],
        "palette.derivation": _literal(wd.PaletteDerivation),
        "typography.pairing": _literal(wd.TypographyPairing),
        "radius": _literal(wd.RadiusScale),
        "density": _literal(wd.DensityScale),
        "sectionOrder": list(wd.MOVABLE_SECTIONS),
        "hero.layout": _literal(wd.HeroLayout),
        "gallery.layout": _literal(wd.GalleryLayout),
        "gallery.maxItems": {"min": wd.GALLERY_MAX_ITEMS_MIN, "max": wd.GALLERY_MAX_ITEMS_MAX},
        "surfaces.mode": _literal(wd.SurfaceMode),
        "cta.variant": _literal(wd.CtaVariant),
        "rationale.maxLength": wd.RATIONALE_MAX_LENGTH,
    } == CONFORMANCE["vocabulary"]
    assert _literal(wd.MovableSection) == list(wd.MOVABLE_SECTIONS)


@pytest.mark.parametrize("name", sorted(CONFORMANCE["valid"]))
def test_valid_direction_parses_and_round_trips_to_identical_json(name):
    raw = CONFORMANCE["valid"][name]

    direction = WebsiteCreativeDirection.model_validate(raw)

    assert direction.model_dump(mode="json") == raw
    assert WebsiteCreativeDirection.model_validate_json(direction.model_dump_json()) == direction


def test_valid_cases_cover_every_strategy():
    for strategy in BrandStrategy:
        assert WebsiteCreativeDirection.model_validate(CONFORMANCE["valid"][strategy.value]).strategy is strategy


@pytest.mark.parametrize("name", sorted(CONFORMANCE["invalid"]))
def test_invalid_direction_is_rejected(name):
    with pytest.raises(ValidationError):
        WebsiteCreativeDirection.model_validate(CONFORMANCE["invalid"][name])


# --- Presentation-only boundary -------------------------------------------


def _free_text_paths(schema: dict, defs: dict, path: str = "") -> list[str]:
    """Every string-typed property that is NOT constrained to a closed
    enum/const — i.e. anything a provider could write arbitrary text into."""
    found: list[str] = []
    if "$ref" in schema:
        return _free_text_paths(defs[schema["$ref"].split("/")[-1]], defs, path)
    for variant in schema.get("anyOf", []) + schema.get("oneOf", []):
        found += _free_text_paths(variant, defs, path)
    if schema.get("type") == "string" and "enum" not in schema and "const" not in schema:
        found.append(path)
    for key, child in schema.get("properties", {}).items():
        found += _free_text_paths(child, defs, f"{path}.{key}" if path else key)
    if "items" in schema:
        found += _free_text_paths(schema["items"], defs, f"{path}[]")
    return found


def test_the_only_free_text_field_is_the_rationale_audit_note():
    schema = WebsiteCreativeDirection.model_json_schema()
    assert sorted(set(_free_text_paths(schema, schema.get("$defs", {})))) == ["rationale"]


def test_every_model_forbids_extra_keys():
    schema = WebsiteCreativeDirection.model_json_schema()
    objects = [schema, *schema.get("$defs", {}).values()]
    for obj in objects:
        if obj.get("type") == "object":
            assert obj.get("additionalProperties") is False, obj.get("title")


def _field_names(schema: dict) -> set[str]:
    names: set[str] = set()
    for obj in [schema, *schema.get("$defs", {}).values()]:
        names |= {name.lower() for name in obj.get("properties", {})}
    return names


def test_the_contract_has_no_business_fact_asset_or_provider_field():
    # Field NAMES only — descriptions (e.g. the reused BrandStrategy enum's
    # docstring) legitimately mention "business".
    field_names = " ".join(sorted(_field_names(WebsiteCreativeDirection.model_json_schema())))
    for forbidden in (
        "business",
        "service_name",
        "price",
        "address",
        "phone",
        "email",
        "whatsapp",
        "review",
        "testimonial",
        "rating",
        "project",
        "claim",
        "url",
        "src",
        "asset_id",
        "font_family",
        "html",
        "css",
        "higgsfield",
        "anthropic",
        "openai",
        "internal",
        "credit",
        "cost",
        "request_id",
    ):
        assert forbidden not in field_names, forbidden


@pytest.mark.parametrize(
    "field",
    ["businessName", "services", "products", "prices", "phone", "email", "reviews", "testimonials", "claims", "html"],
)
def test_a_business_fact_or_markup_field_is_always_rejected(field):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WebsiteCreativeDirection.model_validate({**CONFORMANCE["valid"]["evolve"], field: "anything"})


def test_preserve_must_keep_the_brand_palette():
    raw = {**CONFORMANCE["valid"]["preserve"], "palette": {"mode": "brand_derived", "derivation": "muted"}}
    with pytest.raises(ValidationError, match="preserve"):
        WebsiteCreativeDirection.model_validate(raw)
