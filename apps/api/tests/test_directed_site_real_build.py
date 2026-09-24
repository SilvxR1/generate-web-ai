"""A8.2.3 — directed SiteConfigs through the REAL chain:

    generateSiteConfig(config, assets, direction)   (TypeScript, fixture)
    -> SiteConfigPayload -> create_website_draft -> real `astro build`
    -> PlatformContract

tests/fixtures/a8_directed_site_configs.json is written by
packages/website-generator's direction.test.ts (toMatchFileSnapshot) from the
internal provider's REAL EVOLVE / NEW_DIRECTION directions
(packages/website-generator/fixtures/internal-directions.json, itself
drift-guarded by test_internal_directions_fixture.py). Local only — no
provider, no production."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.business_config import BusinessConfig
from app.domain.enums import WebsiteDraftStatus
from app.publishing import build as build_module
from app.publishing.drafts import create_website_draft
from app.qa.platform_contract import validate_platform_contract
from app.schemas.site_config import SiteConfigPayload

FIXTURES = Path(__file__).parent / "fixtures"
SITE_CONFIGS = json.loads((FIXTURES / "a8_directed_site_configs.json").read_text("utf-8"))
DIRECTIONS = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages" / "website-generator" / "fixtures" / "internal-directions.json"
    ).read_text("utf-8")
)
CASES = [(name, strategy) for name in sorted(SITE_CONFIGS) for strategy in ("evolve", "new_direction")]
_SECTION_ID = re.compile(r'<section\b[^>]*\bid="([\w-]+)"')


def _business_config(name: str) -> BusinessConfig:
    return BusinessConfig.model_validate(DIRECTIONS["cases"][name]["businessConfig"])


@pytest.fixture(scope="module")
def builds() -> dict:
    """One real build per (case, strategy), shared by every test here."""
    return {
        (name, strategy): build_module.build_site(SiteConfigPayload.model_validate(SITE_CONFIGS[name][strategy]))
        for name, strategy in CASES
    }


def _html(builds: dict, name: str, strategy: str) -> str:
    return builds[(name, strategy)].files["index.html"].decode("utf-8")


@pytest.mark.parametrize(("name", "strategy"), CASES)
def test_directed_site_passes_platform_contract_with_zero_blocking_findings(builds, name, strategy):
    result = validate_platform_contract(builds[(name, strategy)].files, business_config=_business_config(name))

    assert [f.message for f in result.blocking_violations] == []


@pytest.mark.parametrize(("name", "strategy"), CASES)
def test_every_in_page_anchor_resolves_and_sections_render_in_direction_order(builds, name, strategy):
    html = _html(builds, name, strategy)
    direction = DIRECTIONS["cases"][name]["directions"][strategy]

    for target in set(re.findall(r'href="#([\w-]+)"', html)):
        assert f'id="{target}"' in html, target
    rendered = [section for section in _SECTION_ID.findall(html) if section in ("services", "gallery", "about")]
    assert rendered == direction["sectionOrder"]
    ids = _SECTION_ID.findall(html)
    assert ids[0] == "hero"
    assert ids[-2:] == ["cta", "contact"]


@pytest.mark.parametrize(("name", "strategy"), CASES)
def test_direction_presentation_reaches_the_rendered_html(builds, name, strategy):
    html = _html(builds, name, strategy)
    direction = DIRECTIONS["cases"][name]["directions"][strategy]

    assert f'data-layout="{direction["hero"]["layout"]}"' in html
    gallery_items = html.count('class="block-gallery__item"')
    assert 0 < gallery_items <= direction["gallery"]["maxItems"]
    featured = len(re.findall(r'class="block-gallery__item"[^>]*data-featured="true"', html))
    assert featured == (1 if direction["gallery"]["layout"] == "featured_grid" else 0)
    if direction["density"] != "comfortable":
        assert "--ui-space-section-md" in html
    assert direction["rationale"] not in html


@pytest.mark.parametrize("name", sorted(SITE_CONFIGS))
def test_refresh_and_new_direction_render_materially_different_html(builds, name):
    evolve, new = _html(builds, name, "evolve"), _html(builds, name, "new_direction")

    assert _SECTION_ID.findall(evolve) != _SECTION_ID.findall(new)
    assert 'data-layout="split"' in evolve and 'data-layout="centered"' in new
    assert evolve.count('class="block-gallery__item"') > new.count('class="block-gallery__item"')
    evolve_style = re.search(r'<html[^>]*style="([^"]*)"', evolve).group(1)
    new_style = re.search(r'<html[^>]*style="([^"]*)"', new).group(1)
    assert evolve_style != new_style  # colours, fonts, radius, spacing tokens


def test_the_same_directed_config_renders_identical_html(builds):
    name, strategy = CASES[0]
    again = build_module.build_site(SiteConfigPayload.model_validate(SITE_CONFIGS[name][strategy]))

    assert again.files["index.html"] == builds[(name, strategy)].files["index.html"]


@pytest.mark.parametrize(("name", "strategy"), [("handmade_shop", "new_direction"), ("renovation", "evolve")])
def test_a_directed_draft_reaches_ready_through_the_real_draft_pipeline(
    session: Session, tenant: Tenant, business: Business, name, strategy
):
    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=SiteConfigPayload.model_validate(SITE_CONFIGS[name][strategy]),
        business_config=_business_config(name),
    )

    assert draft.build_error is None
    assert draft.status is WebsiteDraftStatus.READY
