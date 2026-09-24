"""SiteConfigPayload (app.schemas.site_config) — A8.1.2's block-metadata
round-trip invariant: a Studio/generator-shaped block survives

    API validation -> model_dump() -> (the JSON build_site writes)

with packages/site-config's BlockConfigBase metadata (`id`,
`background`, `reveal`) and PageConfig's optional `seo` intact. Before
this, extra="ignore" silently dropped all of them, so every generated
section rendered without its anchor id (see
test_website_draft_real_build.py for the real-build consequence)."""

import json

import pytest
from pydantic import ValidationError

from app.schemas.site_config import SiteConfigPayload


def _site_config(blocks: list[dict], **page_fields) -> dict:
    return {
        "brand": {"name": "Taller Martinez"},
        "theme": {
            "colors": {
                "primary": "#111827",
                "secondary": "#6b7280",
                "accent": "#2563eb",
                "background": "#ffffff",
                "foreground": "#111827",
            },
            "fonts": {"sans": "Inter, sans-serif"},
            "radius": {"base": "0.5rem", "lg": "1rem"},
        },
        "seo": {"title": "Taller Martinez", "description": "Taller en Valencia."},
        "pages": [{"path": "/", "blocks": blocks, **page_fields}],
    }


def _round_trip(raw: dict) -> dict:
    # Exactly what app.publishing.build.build_site writes to SITE_CONFIG_PATH.
    return json.loads(json.dumps(SiteConfigPayload.model_validate(raw).model_dump(mode="json")))


def test_block_id_background_and_reveal_survive_unchanged():
    block = {
        "type": "services",
        "id": "services",
        "background": "surface",
        "reveal": False,
        "content": {"items": [{"title": "Reparación", "description": "Rápida"}]},
    }

    dumped = _round_trip(_site_config([block]))

    assert dumped["pages"][0]["blocks"] == [block]


def test_every_generator_block_id_is_preserved():
    blocks = [
        {"type": "hero", "id": "hero", "content": {"primaryAction": {"label": "Contactar", "href": "#contact"}}},
        {"type": "services", "id": "services", "background": "base", "content": {"items": []}},
        {"type": "features", "id": "about", "background": "surface", "content": {"items": []}},
        {"type": "cta", "id": "cta", "content": {"heading": "¿Hablamos?"}},
        {"type": "contact", "id": "contact", "content": {"heading": "Contacto"}},
    ]

    dumped = _round_trip(_site_config(blocks))

    assert [b.get("id") for b in dumped["pages"][0]["blocks"]] == ["hero", "services", "about", "cta", "contact"]
    assert dumped["pages"][0]["blocks"] == blocks


def test_omitted_metadata_stays_omitted_never_becomes_null():
    # The Astro blocks default `reveal = true` / `background = "base"` only
    # for an *absent* prop — a JSON null would silently disable reveal.
    dumped = _round_trip(_site_config([{"type": "hero", "content": {"heading": "Hola"}}]))

    block = dumped["pages"][0]["blocks"][0]
    assert block == {"type": "hero", "content": {"heading": "Hola"}}
    assert "seo" not in dumped["pages"][0]


def test_page_level_seo_override_is_preserved():
    seo = {"title": "Privacidad", "description": "Política de privacidad."}

    dumped = _round_trip(_site_config([], seo=seo))

    page_seo = dumped["pages"][0]["seo"]
    assert (page_seo["title"], page_seo["description"]) == (seo["title"], seo["description"])


def test_unknown_background_value_is_a_clean_validation_error():
    with pytest.raises(ValidationError):
        SiteConfigPayload.model_validate(_site_config([{"type": "hero", "background": "neon", "content": {}}]))


@pytest.mark.parametrize("bad_id", ["my section", 'x" onclick="y', ""])
def test_an_id_no_in_page_anchor_could_target_is_rejected(bad_id):
    with pytest.raises(ValidationError):
        SiteConfigPayload.model_validate(_site_config([{"type": "hero", "id": bad_id, "content": {}}]))


def test_unknown_block_keys_are_still_ignored_not_passed_to_the_build():
    dumped = _round_trip(_site_config([{"type": "hero", "id": "hero", "content": {}, "onload": "x"}]))

    assert dumped["pages"][0]["blocks"][0] == {"type": "hero", "id": "hero", "content": {}}


# --- A8.3.2: GalleryItemConfig.title is optional ------------------------------


def test_gallery_items_with_and_without_title_survive_the_round_trip_unchanged():
    items = [
        {"image": {"src": "https://cdn.example.com/a.jpg", "alt": "Foto A"}},
        {
            "title": "Cocina en Ruzafa",
            "category": "Proyecto",
            "image": {"src": "https://cdn.example.com/b.jpg", "alt": "B"},
        },
        {
            "image": {"src": "https://cdn.example.com/c.jpg", "alt": "C"},
            "featured": True,
            "description": "Real caption",
        },
    ]
    block = {"type": "gallery", "id": "gallery", "content": {"heading": "Galería", "items": items, "layout": "grid"}}

    dumped = _round_trip(_site_config([block]))

    assert dumped["pages"][0]["blocks"][0]["content"]["items"] == items
    assert "title" not in dumped["pages"][0]["blocks"][0]["content"]["items"][0]


def test_block_content_stays_opaque_but_block_level_unknown_keys_are_still_dropped():
    # Block `content` is interpreted only by the renderer (this module's
    # documented policy), so its fields pass through untouched; the typed
    # block envelope around it still ignores unknown keys.
    block = {"type": "gallery", "id": "gallery", "content": {"items": []}, "html": "<script>x</script>"}

    dumped = _round_trip(_site_config([block]))

    assert dumped["pages"][0]["blocks"][0] == {"type": "gallery", "id": "gallery", "content": {"items": []}}
