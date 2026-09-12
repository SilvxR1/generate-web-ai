"""app.publishing.build.build_site against the REAL apps/site-builder
Astro app — no mocking. This is the "real Astro output" proof this
phase asks for:

    BusinessConfig (real fixture) -> generateSiteConfig() -> SiteConfig
    -> real `astro build` (@generate-web-ai/renderer/blocks/Tailwind,
       the same pipeline apps/clients/* use) -> WebsiteArtifact

using tests/fixtures/reforma_site_config.json — the actual output of
packages/website-generator's generateSiteConfig(exampleReformaValenciaConfig)
(see that fixture file's header comment for how to regenerate it), the
same object Studio computes for its own website preview and would send
to POST /businesses/{id}/website/publish.

Slower than the rest of the suite (each build genuinely shells out to
`astro build`) — kept in its own module, one shared build per test run.
"""

import json
import re
from pathlib import Path

import pytest

from app.publishing.build import build_site
from app.schemas.site_config import SiteConfigPayload

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reforma_site_config.json"


def _reforma_site_config() -> SiteConfigPayload:
    return SiteConfigPayload.model_validate(json.loads(FIXTURE_PATH.read_text()))


@pytest.fixture(scope="module")
def reforma_artifact():
    return build_site(_reforma_site_config())


@pytest.fixture(scope="module")
def reforma_html(reforma_artifact) -> str:
    return reforma_artifact.files["index.html"].decode("utf-8")


def test_build_produces_the_entry_point_html(reforma_artifact):
    assert "index.html" in reforma_artifact.files
    assert reforma_artifact.entry_point == "index.html"


def test_html_reflects_real_hero_services_cta_and_contact_content(reforma_html):
    assert "Reforma Casa Valencia" in reforma_html
    assert "Cocinas" in reforma_html
    assert "¿Listo para empezar tu proyecto?" in reforma_html
    assert "Contacto" in reforma_html
    assert "+34 960 00 00 00" in reforma_html
    assert 'href="tel:+34960000000"' in reforma_html


def test_html_is_produced_by_the_real_design_system_not_a_simplified_stand_in(reforma_html):
    # These class names come from packages/blocks/packages/ui's real
    # Astro components (Hero.astro, Services.astro, ui-btn, ui-card...) —
    # a from-scratch renderer would never reproduce them by accident.
    assert "block-hero" in reforma_html
    assert "block-services" in reforma_html
    assert "block-cta" in reforma_html
    assert "block-contact" in reforma_html
    assert "ui-btn" in reforma_html
    assert "ui-card" in reforma_html


def test_build_produces_real_compiled_css(reforma_artifact):
    css_files = {path: content for path, content in reforma_artifact.files.items() if path.endswith(".css")}

    assert css_files
    for content in css_files.values():
        assert len(content) > 1000  # a real compiled stylesheet, not an empty placeholder

    combined = b"".join(css_files.values()).decode("utf-8")
    assert "ui-btn" in combined


def test_assets_referenced_in_the_html_all_resolve_in_the_artifact(reforma_html, reforma_artifact):
    referenced = set(re.findall(r'(?:href|src)="(/_astro/[^"]+)"', reforma_html))

    assert referenced  # at minimum, the compiled stylesheet link
    for ref in referenced:
        assert ref.lstrip("/") in reforma_artifact.files


def test_theme_colors_are_applied_without_a_raw_set_html_style_block(reforma_html):
    assert "--ui-color-primary:#f59e0b" in reforma_html


def test_build_never_lets_configurable_content_break_out_as_real_markup():
    malicious = "</style><script>window.__pwned = true;</script>"
    site_config = _reforma_site_config()
    site_config.brand.tagline = malicious

    artifact = build_site(site_config)
    html = artifact.files["index.html"].decode("utf-8")

    assert "<script>window.__pwned" not in html
    assert "</style><script>" not in html
    assert "window.__pwned" not in html or "&lt;script&gt;" in html


def test_contact_form_renders_the_injected_webhook_action_and_predictable_field_names():
    # Mirrors exactly what app.publishing.service._inject_lead_capture_webhook_url
    # does before a real build — proving the *real* Contact.astro (not a
    # hand-rolled stand-in) turns that injected `action` into a genuine
    # <form> attribute, and that its field `name`s stay predictable
    # (name/phone — this fixture's real lead-capture form fields).
    site_config = _reforma_site_config()
    contact = next(b for p in site_config.pages for b in p.blocks if b.type == "contact")
    webhook_url = "https://n8n.example.com/webhook/lead-submitted/reforma-casa-valencia-lead-capture"
    contact.content["form"]["action"] = webhook_url

    artifact = build_site(site_config)
    html = artifact.files["index.html"].decode("utf-8")

    # P2: Contact.astro's form also carries data-gwa-lead-form (the
    # PlatformContract lead-form marker, app.qa.platform_contract) —
    # additive, doesn't change the webhook-wiring assertion this test is
    # actually about.
    assert f'<form class="block-contact__form" data-gwa-lead-form action="{webhook_url}" method="post"' in html
    assert 'name="name"' in html
    assert 'name="phone"' in html


def test_build_produces_the_legal_pages_and_the_footer_links_to_them(reforma_artifact, reforma_html):
    # generateSiteConfig() always adds these three (see
    # packages/website-generator/src/legal.ts) — this proves apps/site-
    # builder's [...slug].astro actually builds them as real routes, not
    # just that they exist in the SiteConfig.
    assert "privacy/index.html" in reforma_artifact.files
    assert "terms/index.html" in reforma_artifact.files
    assert "cookies/index.html" in reforma_artifact.files

    assert 'href="/privacy"' in reforma_html
    assert 'href="/terms"' in reforma_html
    assert 'href="/cookies"' in reforma_html


def test_legal_pages_carry_the_not_legal_advice_disclaimer(reforma_artifact):
    privacy_html = reforma_artifact.files["privacy/index.html"].decode("utf-8")
    terms_html = reforma_artifact.files["terms/index.html"].decode("utf-8")
    cookies_html = reforma_artifact.files["cookies/index.html"].decode("utf-8")

    for html in (privacy_html, terms_html, cookies_html):
        assert "not legal advice" in html
        assert "not been reviewed by a lawyer" in html


def test_cookie_consent_banner_renders_on_every_page_with_no_preselected_optional_consent(reforma_html):
    assert 'id="gwa-consent-banner"' in reforma_html
    assert "Reject non-essential" in reforma_html
    assert "Accept all" in reforma_html
    # Every optional-category checkbox must render unchecked; only the
    # always-on "Necessary" one is checked (P0's "never preselect
    # optional consent as accepted" constraint). Matches the actual
    # <input> elements (attribute value quoted with "), not the bundled
    # script's own `[data-consent-category]` selector string.
    checkbox_matches = re.findall(r'<input type="checkbox"[^>]*data-consent-category="(\w+)"[^>]*>', reforma_html)
    assert sorted(checkbox_matches) == ["analytics", "marketing", "preferences"]
    for category in ("analytics", "marketing", "preferences"):
        assert f'checked data-consent-category="{category}"' not in reforma_html


def test_the_consent_banners_inline_script_is_allow_listed_in_the_generated_csp(reforma_artifact):
    headers_file = reforma_artifact.files["_headers"].decode("utf-8")
    assert "script-src 'self'" in headers_file
    # A real sha256- hash was computed for at least one inline script
    # (the consent banner's own toggle/storage logic) — proves
    # app.publishing.build._inline_script_hashes actually found and
    # allow-listed it, not that the CSP silently fell back to
    # 'unsafe-inline' or blocked the banner from working.
    assert "'sha256-" in headers_file


def test_build_failure_raises_a_clear_error_not_a_silent_empty_artifact():
    from app.publishing.build import SiteBuildError
    from app.schemas.site_config import SiteBlockPayload

    site_config = _reforma_site_config()
    # BlockRenderer.astro's assertKnownBlockType throws for a `type` it
    # doesn't recognize (see packages/renderer/src/BlockRenderer.astro)
    # — a real render failure, not a hand-simulated one.
    site_config.pages[0].blocks.append(SiteBlockPayload(type="not-a-real-block", content={}))

    with pytest.raises(SiteBuildError):
        build_site(site_config)
