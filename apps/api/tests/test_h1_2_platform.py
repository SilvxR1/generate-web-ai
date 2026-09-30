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
from app.creative.source_adapter import platform_files as pf
from app.creative.source_adapter.fixtures import nexo_reformas_business_config
from app.creative.source_adapter.overlays.nexo_reformas import OVERLAY as NEXO_OVERLAY
from app.domain.business_config import BusinessConfig
from app.domain.business_config.business_profile import ContactInfo
from app.domain.business_truth import FactSource, LogoTruth, derive_business_truth
from app.publishing.qa_evidence import QA_EVIDENCE_VERSION, evidence_is_current, visual_qa_evidence
from app.qa.truth_contract import validate_truth_contract

ORIGIN = "https://nexo-reformas.example"


def _truth(config: BusinessConfig | None = None):
    return derive_business_truth(business_config=config or nexo_reformas_business_config())


def _with_profile(**update: object) -> BusinessConfig:
    config = nexo_reformas_business_config()
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


# --- Platform integration content (H2: shared by every export of the family) ---------------------------


def test_structured_data_contains_only_business_truth_facts():
    data = pf.json_ld(_truth(), ORIGIN)
    assert data["@type"] == "HomeAndConstructionBusiness"  # from the vertical, not from the export
    assert data["name"] == "Nexo Reformas" and data["url"] == "https://nexo-reformas.example/"
    assert data["areaServed"] == [{"@type": "City", "name": "Valencia"}]
    assert [o["itemOffered"]["name"] for o in data["makesOffer"]] == ["Reforma integral", "Cocina", "Baño", "Pintura"]
    absent = ("aggregateRating", "review", "telephone", "email", "address", "foundingDate", "priceRange", "logo")
    for invented in absent:
        assert invented not in data  # absent from BusinessTruth -> absent here


def test_structured_data_includes_contact_facts_only_when_business_truth_has_them():
    truth = _truth(_with_profile(contact=ContactInfo(phone="+34 600 000 000")))
    data = pf.json_ld(truth, ORIGIN)
    assert data["telephone"] == truth.contact.phone and "email" not in data


def test_the_business_module_cannot_close_its_script_element():
    config = nexo_reformas_business_config()
    hostile = config.model_copy(
        update={"business_profile": config.business_profile.model_copy(update={"name": "A</script>B"})}
    )
    module = pf.business_module(_truth(hostile), ORIGIN)
    assert "</script>" not in module.split("SITE_JSONLD", 1)[1]


def test_the_open_graph_image_is_owned_deterministic_and_1200x630():
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (30, 60, 50)).save(buffer, format="PNG")
    first, second = pf.derive_og_image(buffer.getvalue()), pf.derive_og_image(buffer.getvalue())
    assert first == second
    with Image.open(io.BytesIO(first)) as image:
        assert image.size == (1200, 630) and image.format == "JPEG"


def test_readiness_blocks_launch_on_missing_legal_identity_and_asks_the_owner_to_confirm_claims():
    findings = pf.readiness(
        _truth(),
        has_generated_icons=True,
        third_party_services=("cabinet-grotesk",),
        owner_review_claims=NEXO_OVERLAY.owner_review_claims,
        unverified_claims=[],
    )
    codes = [(f["code"], f["severity"]) for f in findings]
    assert codes.count(("legal_identity_missing", "launch_blocker")) == 4
    assert ("logo_not_provided", "info") in codes and ("favicon_from_generated_mark", "owner_review") in codes
    assert ("form_only_contact", "info") in codes and ("third_party_font_service", "owner_review") in codes
    assert sum(1 for code, _ in codes if code == "claim_needs_owner_confirmation") == len(
        NEXO_OVERLAY.owner_review_claims
    )


def test_the_legal_content_is_in_the_site_language_and_discloses_third_parties():
    legal = json.loads(pf.legal_content_json(_truth(), "es", ("Fontshare (prueba)",)))
    assert legal["lang"] == "es" and legal["pages"]["terms"]["title"] == "Aviso legal"
    assert legal["pages"]["privacy"]["metaTitle"] == "Política de privacidad — Nexo Reformas"
    assert any("Fontshare (prueba)" in p for p in legal["pages"]["cookies"]["paragraphs"])
    english = json.loads(pf.legal_content_json(_truth(), "en", ()))
    assert english["lang"] == "en" and english["pages"]["privacy"]["title"] != legal["pages"]["privacy"]["title"]
    assert "Aviso legal" in pf.legal_links_tsx("es", None, "nx-mono") and 'className="nx-mono"' in pf.legal_links_tsx(
        "es", None, "nx-mono"
    )


def test_the_legal_page_heads_are_canonical():
    for tsx in (pf.default_legal_page_tsx("en"), NEXO_OVERLAY.legal.page_tsx):  # type: ignore[union-attr]
        assert tsx is not None and 'rel: "canonical"' in tsx and "lang={legal.lang}" in tsx
