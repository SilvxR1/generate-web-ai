"""validate_site_config (app.qa.validate): the small, fixed set of
structural/content checks Phase 17 asks for — never a fabrication check
on content this backend doesn't generate itself."""

import json

from app.qa.validate import validate_site_config
from app.schemas.site_config import SiteConfigPayload

_VALID = {
    "brand": {"name": "Acme"},
    "theme": {
        "colors": {
            "primary": "#000",
            "secondary": "#111",
            "accent": "#222",
            "background": "#fff",
            "foreground": "#000",
        },
        "fonts": {"sans": "Inter"},
        "radius": {"base": "0.5rem", "lg": "1rem"},
    },
    "seo": {"title": "Acme", "description": "A great business."},
    "pages": [{"path": "/", "blocks": [{"type": "hero", "content": {}}]}],
}


def _config(**overrides) -> SiteConfigPayload:
    data = json.loads(json.dumps(_VALID))
    for key, value in overrides.items():
        data[key] = value
    return SiteConfigPayload.model_validate(data)


def test_valid_config_has_no_issues():
    assert validate_site_config(_config()) == []


def test_missing_hero_is_flagged():
    config = _config()
    config.pages[0].blocks = [b for b in config.pages[0].blocks if b.type != "hero"]

    issues = validate_site_config(config)

    assert any("hero" in issue for issue in issues)


def test_empty_seo_title_is_flagged():
    config = _config()
    config.seo.title = "   "

    issues = validate_site_config(config)

    assert any("SEO title" in issue for issue in issues)


def test_empty_testimonials_section_is_flagged_without_calling_it_fabrication():
    config = _config()
    config.pages[0].blocks.append(
        type(config.pages[0].blocks[0])(type="testimonials", content={"items": []})
    )

    issues = validate_site_config(config)

    assert any("no reviews" in issue for issue in issues)


def test_contact_form_enabled_without_contact_section_is_flagged():
    config = _config()
    config.features = {"contactForm": True}

    issues = validate_site_config(config)

    assert any("no contact section" in issue for issue in issues)


def test_no_pages_is_flagged():
    config = _config()
    config.pages = []

    issues = validate_site_config(config)

    assert issues == ["Site has no pages."]
