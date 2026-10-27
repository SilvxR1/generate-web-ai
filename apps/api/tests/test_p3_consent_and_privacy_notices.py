"""P3 — the consent banner and the legal pages describe only what GWA sites do.

Measured behaviour of a GWA site (no cookies; `gwa-consent` in localStorage
after a choice; first-party analytics events only after "analytics" is
accepted; on TanStack exports, TanStack Router's own sessionStorage) is
what the visitor is told — nothing about Marketing or Preferences, which no
GWA site uses, and no claim that contact data feeds analytics or advertising.
Covers both banners (imported/generative fragment and the Astro component)
and both legal sources (legal_pages.py; legal-es.ts is covered by the
website-generator's own tests). The browser test runs the real banner
script in Chromium.
"""

import functools
import http.server
import json
import re
import shutil
import threading
from pathlib import Path

import pytest

from app.creative.frontend_engine.browser_qa import check_browser_qa_availability
from app.creative.frontend_engine.build import PLATFORM_CONSENT_FRAGMENTS, inject_platform_runtime
from app.creative.frontend_engine.legal_pages import legal_page_content
from app.creative.source_adapter.fixtures import lumen_physio_business_config, zip_directory
from app.creative.source_adapter.pipeline import plan_export
from app.creative.source_adapter.platform_files import TECHNICAL_STORAGE_DISCLOSURES
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import derive_business_truth

REPO = Path(__file__).resolve().parents[3]
ASTRO_BANNER = REPO / "apps" / "site-builder" / "src" / "components" / "CookieConsentBanner.astro"
ASTRO_STRINGS = REPO / "apps" / "site-builder" / "src" / "lib" / "i18n.ts"
LUMEN = Path(__file__).parent / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
AVAILABLE, UNAVAILABLE_REASON = check_browser_qa_availability()


def _truth():
    config = BusinessConfig.model_validate(
        {
            "business_profile": {"name": "Taller Ficticio", "slug": "taller-ficticio", "industry": "other",
                                 "contact": {"email": "hola@taller-ficticio.example"}},
            "lead_management": {"enabled": True, "consent_required": True},
        }
    )  # fmt: skip
    return derive_business_truth(business_config=config)


# --- banners --------------------------------------------------------------------------------------


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_platform_banner_offers_only_the_categories_that_exist(locale):
    fragment = PLATFORM_CONSENT_FRAGMENTS[locale]
    assert re.findall(r'data-consent-category="(\w+)"', fragment) == ["analytics"]
    assert "Marketing" not in fragment and "Preferencias</label>" not in fragment
    assert "Preferences</label>" not in fragment
    assert "apply({analytics:true,marketing:false,preferences:false})" in fragment  # "accept" = analytics only
    assert "marketing:true" not in fragment and "preferences:true" not in fragment
    text = re.search(r"<p>(.*?)</p>", fragment).group(1)
    assert ("sin cookies" if locale == "es" else "without cookies") in text
    assert "usa cookies" not in text and "uses cookies" not in text


def test_the_astro_banner_offers_only_the_categories_that_exist():
    banner, strings = ASTRO_BANNER.read_text(encoding="utf-8"), ASTRO_STRINGS.read_text(encoding="utf-8")
    assert re.findall(r'data-consent-category="(\w+)"', banner) == ["analytics"]
    assert "applyAndClose({ analytics: true, marketing: false, preferences: false })" in banner
    assert "marketing:" not in strings and "preferences:" not in strings
    assert "This site uses cookies" not in strings and "sin cookies" in strings and "without cookies" in strings


# --- legal pages ----------------------------------------------------------------------------------


def test_the_spanish_privacy_page_describes_contact_messages_accurately():
    privacy = " ".join(legal_page_content(_truth(), locale="es")["privacy"][1])
    assert "se usan solo para responder a tu mensaje. No se usan para publicidad ni para estadísticas." in privacy
    assert "se envía por email al titular" in privacy
    assert "para analítica" not in privacy
    assert "Agencia Española de Protección de Datos (www.aepd.es)" in privacy


def test_the_english_privacy_page_describes_contact_messages_accurately():
    privacy = " ".join(legal_page_content(_truth(), locale="en")["privacy"][1])
    assert "used only to reply to your message. It is not used for advertising or for statistics." in privacy
    assert "for analytics" not in privacy


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_cookie_page_names_the_real_storage_and_what_analytics_sends(locale):
    storage = (TECHNICAL_STORAGE_DISCLOSURES["tanstack-router"][locale],)
    cookies = legal_page_content(_truth(), locale=locale, technical_storage=storage)["cookies"][1]
    text = " ".join(cookies)
    assert "gwa-consent" in text
    expected = "sin cookies y sin identificadores personales" if locale == "es" else "without personal identifiers"
    assert expected in text
    assert any("TanStack Router" in p for p in cookies)
    assert "marketing" not in text.lower()
    without = " ".join(legal_page_content(_truth(), locale=locale)["cookies"][1])
    assert "TanStack Router" not in without  # only disclosed where the family uses it


def test_an_imported_tanstack_site_discloses_tanstack_router_storage(tmp_path):
    source = tmp_path / "v" / "lumen-physio"
    shutil.copytree(LUMEN, source)
    zip_path = zip_directory(source, tmp_path / "v.zip")
    planned = plan_export(zip_path, tmp_path / "work", lumen_physio_business_config(),
                          site_origin="https://lumen-physio.example")  # fmt: skip
    [content] = [op for op in planned.plan.operations if op.path == "src/platform/legal-content.json"]
    pages = json.loads(content.content)["pages"]
    assert any("TanStack Router" in p for p in pages["cookies"]["paragraphs"])


# --- the real banner in a browser -----------------------------------------------------------------


@pytest.fixture()
def served_page(tmp_path):
    html = "<!doctype html><html lang='es'><head><meta charset='utf-8'></head><body><h1>Prueba</h1></body></html>"
    page = inject_platform_runtime(html, business_id="00000000-0000-0000-0000-000000000000", api_base_url=None,
                                   locale="es")  # fmt: skip
    (tmp_path / "index.html").write_text(page, encoding="utf-8")

    class _Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()


@pytest.mark.skipif(not AVAILABLE, reason=f"Playwright/Chromium unavailable: {UNAVAILABLE_REASON}")
@pytest.mark.parametrize(("button", "expected"), [("#gwa-consent-accept", True), ("#gwa-consent-reject", False)])
def test_the_banner_stores_only_the_choice_and_sets_no_cookie(served_page, button, expected):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(served_page)
        visible_before = page.locator("#gwa-consent-banner").is_visible()
        stored_before = page.evaluate("localStorage.length")
        page.click(button)
        record = json.loads(page.evaluate("localStorage.getItem('gwa-consent')"))
        keys = page.evaluate("Object.keys(localStorage)")
        cookies = context.cookies()
        context.close()
        browser.close()

    assert visible_before and stored_before == 0  # nothing stored before a choice
    assert keys == ["gwa-consent"]
    assert (record["analytics"], record["marketing"], record["preferences"]) == (expected, False, False)
    assert cookies == []
