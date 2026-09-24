"""A8.2.3 drift guard for packages/website-generator/fixtures/internal-directions.json.

That fixture carries the REAL WebsiteCreativeDirections the internal provider
(A8.2.2) derives for two representative businesses, so website-generator's
TypeScript tests and the real-build fixtures consume exactly what production
would produce rather than hand-written directions. This test re-derives every
direction through InternalCreativeProvider and must equal the fixture; if the
derivation changes, the fixture must be regenerated deliberately."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.creative.internal import InternalCreativeProvider
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG, BusinessConfig
from app.domain.creative import build_creative_brief
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BrandStrategy

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "packages" / "website-generator" / "fixtures" / "internal-directions.json"
)


def _photo(category: str, n: int, origin: str = "uploaded") -> dict:
    return {
        "kind": "image",
        "category": category,
        "origin": origin,
        "storage_url": f"https://cdn.example.com/{category}-{n}.jpg",
        "alt_text": None,
    }


# Representative businesses, NOT a specific real customer: a branded
# renovation company with project photos (construction family) and a
# branded handmade shop with a large product catalogue (artisan family,
# the "1 hero + 37 gallery photos" shape the A8 owner test exposed).
CASES: dict[str, dict] = {
    "renovation": {
        "businessConfig": EXAMPLE_REFORMA_VALENCIA_CONFIG.model_dump(mode="json"),
        "assets": [_photo("hero_candidate", 0), *[_photo("project", n) for n in range(1, 13)]],
    },
    "handmade_shop": {
        "businessConfig": {
            "schema_version": 1,
            "business_profile": {
                "name": "Taller de Hilo",
                "slug": "taller-de-hilo",
                "industry": "other",
                "description": "Piezas de crochet hechas a mano en Valencia.",
                "services": [
                    {"id": "encargos", "name": "Encargos", "description": "Piezas personalizadas por encargo."},
                    {"id": "talleres", "name": "Talleres", "description": "Clases de crochet en grupo."},
                ],
                "contact": {"email": "hola@example.com", "phone": "+34 600 111 222"},
                "service_area": ["Valencia"],
            },
            "lead_management": {
                "enabled": True,
                "sources": ["website_form"],
                "required_fields": ["name", "email", "message"],
            },
            "brand": {
                "colors": {
                    "primary": "#b5651d",
                    "secondary": "#6b4226",
                    "accent": "#e8a33d",
                    "background": "#fdf8f3",
                    "foreground": "#3a2e28",
                },
                "typography": {"sans": "Inter, sans-serif"},
                "visual_style": "handmade, colourful",
            },
        },
        "assets": [_photo("gallery", n) for n in range(38)],
    },
}


def _brief_assets(assets: list[dict]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=uuid.uuid5(uuid.NAMESPACE_URL, asset["storage_url"]),
            kind=AssetKind(asset["kind"]),
            category=AssetCategory(asset["category"]),
            origin=AssetOrigin(asset["origin"]),
            storage_url=asset["storage_url"],
            storage_provider=None,
            storage_key=None,
            unavailable_reason=None,
            alt_text=asset["alt_text"],
        )
        for asset in assets
    ]


def derive_case(case: dict) -> dict:
    config = BusinessConfig.model_validate(case["businessConfig"])
    directions = {}
    for strategy in BrandStrategy:
        brief = build_creative_brief(
            business_config=config, assets=_brief_assets(case["assets"]), brand_strategy=strategy
        )
        direction = InternalCreativeProvider().generate_website(brief).website_direction
        assert direction is not None
        directions[strategy.value] = direction.model_dump(mode="json")
    return directions


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text("utf-8"))


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_directions_equal_the_internal_providers_real_output(name):
    fixture_case = _fixture()["cases"][name]

    assert fixture_case["businessConfig"] == CASES[name]["businessConfig"]
    assert fixture_case["assets"] == CASES[name]["assets"]
    assert fixture_case["directions"] == derive_case(CASES[name])
