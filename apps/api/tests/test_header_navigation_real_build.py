"""A8.3.3 — the generated header + navigation through the REAL astro build
and PlatformContract. Fixtures are written by packages/website-generator
(navigation.test.ts → a8_header_site_configs.json; direction.test.ts →
a8_directed_site_configs.json). Local only."""

import copy
import json
import re
from pathlib import Path

import pytest

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical
from app.publishing import build as build_module
from app.qa.platform_contract import validate_platform_contract
from app.schemas.site_config import SiteConfigPayload

FIXTURES = Path(__file__).parent / "fixtures"
HEADER_CASES = json.loads((FIXTURES / "a8_header_site_configs.json").read_text("utf-8"))
DIRECTED = json.loads((FIXTURES / "a8_directed_site_configs.json").read_text("utf-8"))

# Lead capture enabled with a website form: the same contract the fixtures'
# businesses are generated under.
CONTRACT_CONFIG = BusinessConfig(
    business_profile=BusinessProfile(name="Taller", slug="taller", industry=BusinessVertical.OTHER)
)

CASES = {
    **HEADER_CASES,
    "tagline_renovation_evolve": DIRECTED["renovation"]["evolve"],
    "no_tagline_handmade_new_direction": DIRECTED["handmade_shop"]["new_direction"],
}


@pytest.fixture(scope="module")
def builds() -> dict:
    return {name: build_module.build_site(_payload(site)) for name, site in CASES.items()}


def _payload(site: dict) -> SiteConfigPayload:
    # The real draft/publish pipeline always sets businessId server-side
    # before building (app.publishing.drafts / service); mirror it so the
    # built site has a usable lead endpoint (A8.3.4-P0 contract rule).
    payload = SiteConfigPayload.model_validate(site)
    payload.businessId = "00000000-0000-4000-8000-000000000001"
    return payload


def _html(builds, name) -> str:
    return builds[name].files["index.html"].decode("utf-8")


def _header(html: str) -> str:
    return re.search(r"<header class=\"site-header\".*?</header>", html, re.S).group(0)


@pytest.mark.parametrize("name", sorted(CASES))
def test_valid_generated_site_has_zero_blocking_platform_contract_findings(builds, name):
    result = validate_platform_contract(builds[name].files, business_config=CONTRACT_CONFIG)
    assert [f.message for f in result.blocking_violations] == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_header_link_resolves_and_follows_rendered_section_order(builds, name):
    html = _html(builds, name)
    header = _header(html)
    desktop = re.search(r'<ul class="site-nav__list".*?</ul>', header, re.S).group(0)
    nav_hrefs = re.findall(r'href="#([\w-]+)"', desktop)
    sections = re.findall(r'<section\b[^>]*\bid="([\w-]+)"', html)

    assert nav_hrefs == [item["href"][1:] for item in CASES[name]["navigation"]]
    for target in nav_hrefs:
        assert target in sections
    assert nav_hrefs == [s for s in sections if s in nav_hrefs]  # same order as the page
    assert "hero" not in nav_hrefs and "cta" not in nav_hrefs
    # The mobile disclosure carries the same links.
    mobile = re.search(r'<details class="site-nav__menu".*?</details>', header, re.S).group(0)
    assert "<summary" in mobile
    assert re.findall(r'href="#([\w-]+)"', mobile) == nav_hrefs


def test_missing_sections_get_no_link(builds):
    header = _header(_html(builds, "no_logo_missing_sections_long_name"))
    assert re.findall(r'href="#([\w-]+)"', header.split("<details")[0]) == ["services", "contact"]
    for absent in ("about", "gallery"):
        assert f'href="#{absent}"' not in header


def test_logo_and_no_logo_fallback(builds):
    with_logo = _header(_html(builds, "full_with_logo"))
    assert 'class="site-header__logo"' in with_logo and 'alt="Logo de Taller Ovillo"' in with_logo

    no_logo = _header(_html(builds, "no_logo_missing_sections_long_name"))
    assert "<img" not in no_logo
    assert "Reformas Sur, Instalaciones y Mantenimiento Integral del Hogar" in no_logo


def test_a_real_tagline_is_in_the_hero_but_not_repeated_in_the_header(builds):
    site = CASES["tagline_renovation_evolve"]
    tagline = site["brand"]["tagline"]
    html = _html(builds, "tagline_renovation_evolve")
    hero = re.search(r'<section[^>]*id="hero".*?</section>', html, re.S).group(0)

    assert tagline and tagline in hero
    assert tagline not in _header(html)
    assert "site-header__tagline" not in html


def test_no_tagline_site_keeps_the_a832_hero_sentence(builds):
    site = CASES["no_tagline_handmade_new_direction"]
    hero_copy = next(b for b in site["pages"][0]["blocks"] if b["type"] == "hero")["content"]["subheading"]
    assert hero_copy and hero_copy in _html(builds, "no_tagline_handmade_new_direction")


def test_a_hand_built_link_to_a_missing_section_is_still_blocked_by_platform_contract():
    broken = copy.deepcopy(CASES["no_logo_missing_sections_long_name"])
    broken["navigation"].append({"label": "Galería", "href": "#gallery"})  # no gallery section renders

    files = build_module.build_site(_payload(broken)).files
    result = validate_platform_contract(files, business_config=CONTRACT_CONFIG)

    assert any(f.rule == "broken_anchor_target" and '"#gallery"' in f.message for f in result.blocking_violations)
