"""H1.2 — platform pieces of the Higgsfield functional integration: bound
QA evidence, Spanish consent/legal, the brand/logo policy, lazy-image QA
and the Nexo mapping's BusinessTruth, SEO and readiness behavior."""

import io
import json
import re

import pytest
from PIL import Image

from app.creative.frontend_engine.browser_qa import _csp_authorized_origins, run_browser_qa
from app.creative.frontend_engine.build import (
    PLATFORM_CONSENT_FRAGMENT,
    PLATFORM_CONSENT_FRAGMENTS,
    inject_platform_runtime,
)
from app.creative.frontend_engine.legal_pages import legal_owner_input_required, legal_page_content
from app.creative.source_adapter.mapping import BusinessTruthGapError, SiteContext
from app.creative.source_adapter.mappings import nexo_reformas as nexo
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.business_profile import ContactInfo, Location, ServiceOffering
from app.domain.business_truth import FactSource, LogoTruth, derive_business_truth
from app.domain.enums import BusinessVertical
from app.publishing.qa_evidence import QA_EVIDENCE_VERSION, evidence_is_current, visual_qa_evidence
from app.qa.truth_contract import validate_truth_contract

SITE = SiteContext(origin="https://nexo-reformas.example", locale="es")


def _truth(config: BusinessConfig | None = None):
    return derive_business_truth(business_config=config or nexo.h1_fixture_business_config())


def _with_profile(**update: object) -> BusinessConfig:
    config = nexo.h1_fixture_business_config()
    return config.model_copy(update={"business_profile": config.business_profile.model_copy(update=update)})


# --- QA evidence bound to the artifact identity ------------------------------------------


def test_evidence_is_current_only_for_the_exact_artifact_identity():
    state = visual_qa_evidence(passed=True, findings=[], artifact_sha256="a" * 64, headers_sha256="h", source="x")
    assert state["evidence_version"] == QA_EVIDENCE_VERSION and state["artifact_sha256"] == "a" * 64
    assert evidence_is_current(state, "a" * 64)
    assert not evidence_is_current(state, "b" * 64)  # content changed: never silently reused
    assert not evidence_is_current(state, None)
    assert not evidence_is_current({"passed": True, "findings": []}, "a" * 64)  # pre-H1.2 evidence names no artifact
    legacy_rebuild = visual_qa_evidence(passed=True, findings=[], artifact_sha256=None, headers_sha256=None, source="x")
    assert not evidence_is_current(legacy_rebuild, "a" * 64)


# --- Spanish consent -----------------------------------------------------------------------


def _script(fragment: str) -> str:
    match = re.search(r"<script>.*</script>", fragment, re.S)
    assert match is not None
    return match.group(0)


def test_the_spanish_banner_has_the_same_controls_and_the_identical_script():
    es = PLATFORM_CONSENT_FRAGMENTS["es"]
    assert PLATFORM_CONSENT_FRAGMENTS["en"] == PLATFORM_CONSENT_FRAGMENT  # English unchanged
    for control in ("gwa-consent-banner", "gwa-consent-accept", "gwa-consent-reject", "gwa-consent-save"):
        assert f'id="{control}"' in es
    assert _script(es) == _script(PLATFORM_CONSENT_FRAGMENT)  # same behavior, same CSP hash
    for text in ("Rechazar no esenciales", "Aceptar todo", "Guardar preferencias", "Analítica", 'href="/cookies"'):
        assert text in es


def test_injection_uses_the_requested_locale_and_refuses_unknown_ones():
    html = "<html><head></head><body></body></html>"
    assert "Aceptar todo" in inject_platform_runtime(html, business_id="b", api_base_url=None, locale="es")
    assert "Accept all" in inject_platform_runtime(html, business_id="b", api_base_url=None)
    with pytest.raises(ValueError):
        inject_platform_runtime(html, business_id="b", api_base_url=None, locale="xx")


# --- Spanish legal pages ----------------------------------------------------------------------


def test_spanish_legal_pages_state_missing_identity_as_not_provided_and_flag_it():
    truth = _truth()
    pages = legal_page_content(truth, locale="es", third_parties=("Fontshare (prueba)",))
    assert [pages[s][0] for s in ("privacy", "terms", "cookies")] == [
        "Política de privacidad",
        "Aviso legal",
        "Política de cookies",
    ]
    assert "NIF: no facilitado." in pages["terms"][1]
    assert any("Fontshare (prueba)" in p for p in pages["cookies"][1])
    assert not any("Fontshare" in p for p in pages["privacy"][1] + pages["terms"][1])
    assert legal_owner_input_required(truth) == [
        "legal.legal_name",
        "legal.tax_id",
        "legal.registered_address",
        "legal.privacy_contact_email",
    ]
    with pytest.raises(ValueError):
        legal_page_content(truth, locale="fr")


# --- Brand / logo policy (TruthContract) ---------------------------------------------------------


def _page_with(img: str) -> dict[str, bytes]:
    return {"index.html": f"<html><body><h1>Nexo Reformas</h1>{img}</body></html>".encode()}


def _logo_rules(files: dict[str, bytes], truth) -> set[str]:
    result = validate_truth_contract(files, business_truth=truth)
    return {f.rule for f in result.violations if "logo" in f.rule}


def test_an_image_in_a_brand_link_is_a_logo_and_needs_an_owner_approved_one():
    mark = '<a class="nx-nav__brand" href="#inicio"><img alt="" class="nx-nav__mark" src="/assets/kit/nexo-mark.png">'
    assert _logo_rules(_page_with(mark + "Nexo Reformas</a>"), _truth()) == {"truth.assets.fabricated_logo"}


def test_an_owner_approved_logo_in_the_brand_link_passes():
    owner_logo = LogoTruth(source=FactSource.OWNER_PROVIDED, url="https://cdn.example/nexo-logo.png")
    truth = _truth().model_copy(update={"logo": owner_logo})
    assert truth.logo is not None
    link = f'<a class="nx-nav__brand" href="/"><img alt="" src="{truth.logo.url}">Nexo Reformas</a>'
    assert _logo_rules(_page_with(link), truth) == set()


def test_brand_in_alt_text_is_not_a_logo_hint():
    photo = '<img alt="A brand new kitchen" src="/assets/kit/macro-roble.jpg">'
    assert _logo_rules(_page_with(photo), _truth()) == set()


# --- Lazy images in Visual QA ----------------------------------------------------------------------


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 90, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


def _qa_images(body: str, files: dict[str, bytes] | None = None):
    page = f"<!doctype html><html><head><title>t</title></head><body><h1>x</h1>{body}</body></html>".encode()
    result = run_browser_qa({"index.html": page, **(files or {})}, viewports=(("desktop", 1024, 768),))
    return next(f for f in result.findings if f.viewport == "desktop" and f.check == "no_broken_images")


_SPACER = '<div style="height: 6000px"></div>'


def test_a_lazy_image_far_down_the_page_is_loaded_before_judging():
    finding = _qa_images(_SPACER + '<img loading="lazy" src="/late.png" alt="">', {"late.png": _png()})
    assert finding.passed, finding.detail


def test_a_genuinely_broken_lazy_image_is_still_detected():
    finding = _qa_images(_SPACER + '<img loading="lazy" src="/missing.png" alt="">')
    assert not finding.passed and "/missing.png" in finding.detail


def test_a_never_rendered_lazy_image_is_reported_not_failed():
    finding = _qa_images('<div style="display:none"><img loading="lazy" src="/hover.png" alt=""></div>')
    assert finding.passed and "1 lazy image(s) never rendered" in finding.detail


def test_offline_qa_stubs_only_the_exact_font_and_style_origins_the_csp_authorizes():
    csp = (
        "default-src 'self'; script-src 'self' https://evil.example; "
        "style-src 'self' 'unsafe-inline' https://api.fontshare.com; "
        "font-src 'self' https://cdn.fontshare.com https://*.wild.example data:; connect-src 'self' https://api.example"
    )
    assert _csp_authorized_origins(csp) == {"https://api.fontshare.com", "https://cdn.fontshare.com"}
    assert _csp_authorized_origins(None) == frozenset()


# --- Nexo mapping: BusinessTruth, SEO, OG image, readiness ---------------------------------------------


def test_every_service_the_site_presents_must_exist_in_business_truth():
    config = nexo.h1_fixture_business_config()
    services = [s for s in config.business_profile.services if s.id != "pintura"]
    with pytest.raises(BusinessTruthGapError, match="pintura"):
        nexo.new_files(_truth(_with_profile(services=services)), SITE)


def test_service_names_come_from_business_truth():
    config = nexo.h1_fixture_business_config()
    renamed = [
        s.model_copy(update={"name": "Baños completos"}) if s.id == "bano" else s
        for s in config.business_profile.services
    ]
    files = nexo.new_files(_truth(_with_profile(services=renamed)), SITE)
    business = next(f for f in files if f.path == "src/platform/business.ts")
    assert '"bano": "Baños completos"' in business.content  # type: ignore[union-attr]


def test_structured_data_contains_only_business_truth_facts():
    truth = _truth()
    data = nexo._json_ld(truth, SITE, nexo._services(truth))
    assert data["name"] == "Nexo Reformas" and data["url"] == "https://nexo-reformas.example/"
    assert data["areaServed"] == [{"@type": "City", "name": "Valencia"}]
    assert [o["itemOffered"]["name"] for o in data["makesOffer"]] == ["Reforma integral", "Cocina", "Baño", "Pintura"]
    absent = ("aggregateRating", "review", "telephone", "email", "address", "foundingDate", "priceRange", "logo")
    for invented in absent:
        assert invented not in data  # absent from BusinessTruth -> absent here


def test_structured_data_includes_contact_facts_only_when_business_truth_has_them():
    truth = _truth(_with_profile(contact=ContactInfo(phone="+34 600 000 000")))
    data = nexo._json_ld(truth, SITE, nexo._services(truth))
    assert data["telephone"] == truth.contact.phone and "email" not in data


def test_the_open_graph_image_is_owned_deterministic_and_1200x630(tmp_path):
    poster = tmp_path / "public/assets/world/nexo-06-poster.png"
    poster.parent.mkdir(parents=True)
    Image.new("RGB", (1920, 1080), (30, 60, 50)).save(poster)
    first, second = nexo.derived_files(tmp_path), nexo.derived_files(tmp_path)
    assert first[0].path == "public/og-image.jpg" and first[0].content == second[0].content
    with Image.open(io.BytesIO(first[0].content)) as image:
        assert image.size == (1200, 630) and image.format == "JPEG"
    [og] = nexo.json_sets(_truth(), SITE)
    assert og.key == "og_image_url" and og.value == "https://nexo-reformas.example/og-image.jpg"


def test_readiness_blocks_launch_on_missing_legal_identity_and_asks_the_owner_to_confirm_claims():
    codes = [(f.code, f.severity) for f in nexo.readiness(_truth())]
    assert codes.count(("legal_identity_missing", "launch_blocker")) == 4
    assert ("logo_not_provided", "info") in codes and ("favicon_from_generated_mark", "owner_review") in codes
    assert ("form_only_contact", "info") in codes
    assert sum(1 for code, _ in codes if code == "claim_needs_owner_confirmation") == len(nexo.OWNER_REVIEW_CLAIMS)


def test_the_legal_content_module_is_spanish_and_canonical():
    files = {f.path: f for f in nexo.new_files(_truth(), SITE)}
    legal = json.loads(files["src/platform/legal-content.json"].content)  # type: ignore[arg-type]
    assert legal["lang"] == "es" and legal["pages"]["terms"]["title"] == "Aviso legal"
    assert "canonical" in files["src/components/nexo/legal-page.tsx"].content  # type: ignore[operator]
    assert "Aviso legal" in files["src/components/nexo/legal-links.tsx"].content  # type: ignore[operator]


def test_an_unrelated_business_cannot_be_mapped_onto_this_export():
    other = BusinessConfig(
        business_profile=BusinessProfile(
            name="Otra",
            slug="otra",
            industry=BusinessVertical.HOME_RENOVATION,
            location=Location(city="Madrid", country="ES"),
            services=[ServiceOffering(id="fontaneria", name="Fontanería", description="x")],
        )
    )
    with pytest.raises(BusinessTruthGapError):
        nexo.new_files(_truth(other), SITE)
