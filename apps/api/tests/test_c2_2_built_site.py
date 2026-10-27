"""C2.2: what C2.1 added to the site builder, checked on REAL local builds.

C2.1 introduced the Spanish chrome (lang, Open Graph locale), canonical URLs,
LocalBusiness JSON-LD, robots.txt, sitemap.xml, a real 404 page and the
consent-aware contact form. Its own tests cover the generator and the API;
these build two fictional fixtures with the real `astro build` (offline, no
publishing) and assert on the files a host would serve:

- "canonical": Taller de Hilo with a verified https siteUrl (what an active
  custom domain gives) and the generator's consent checkbox
  (consent_required);
- "preview": Reforma Casa Valencia with no siteUrl, as every draft preview
  and *.pages.dev build is, and an optional message field.

Every URL here is fictional (`.example`, RFC 2606).
"""

import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from app.publishing import build as build_module
from app.schemas.site_config import SiteConfigPayload

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "a8_directed_site_configs.json").read_text("utf-8"))
ORIGIN = "https://www.taller-de-hilo.example"
PAGES = ("index.html", "aviso-legal/index.html", "privacidad/index.html", "cookies/index.html")
CANONICAL_PATHS = {
    "index.html": "/",
    "aviso-legal/index.html": "/aviso-legal/",
    "privacidad/index.html": "/privacidad/",
    "cookies/index.html": "/cookies/",
}
# The generator's own C2.1 consent field (packages/website-generator/src/blocks.ts).
CONSENT_FIELD = {
    "name": "consent",
    "label": "Protección de datos",
    "type": "checkbox",
    "required": True,
    "placeholder": "He leído y acepto la política de privacidad.",
}
# app.publishing.security_headers' rule for the default Pages host.
PAGES_DEV_NOINDEX = "https://:project.pages.dev/*\n  X-Robots-Tag: noindex"
PRODUCTION_HOSTS = re.compile(r"railway\.app|rlwy\.net|cositasypuntos\.com|pages\.dev|r2\.dev|workers\.dev")


def _site(name: str, *, site_url: str | None, consent: bool) -> SiteConfigPayload:
    site = copy.deepcopy(FIXTURES[name]["undirected"])
    if consent:
        _form(site)["fields"].append(dict(CONSENT_FIELD))
    payload = SiteConfigPayload.model_validate(site)
    payload.businessId = "00000000-0000-4000-8000-000000000001"  # set server-side in the real pipeline
    payload.siteUrl = site_url
    return payload


def _form(site: dict) -> dict:
    return next(b for p in site["pages"] for b in p["blocks"] if b["type"] == "contact")["content"]["form"]


@pytest.fixture(scope="module")
def builds() -> dict:
    return {
        "canonical": build_module.build_site(_site("handmade_shop", site_url=ORIGIN, consent=True)),
        "preview": build_module.build_site(_site("renovation", site_url=None, consent=False)),
    }


def _text(builds: dict, build: str, path: str) -> str:
    return builds[build].files[path].decode("utf-8")


def _head(html: str) -> str:
    return html.split("</head>", 1)[0]


def _meta(html: str, attribute: str, key: str) -> list[str]:
    return re.findall(rf'<meta {attribute}="{re.escape(key)}" content="([^"]*)"', _head(html))


def _canonical(html: str) -> list[str]:
    return re.findall(r'<link rel="canonical" href="([^"]*)"', _head(html))


def _json_ld(html: str) -> list[dict]:
    return [json.loads(raw) for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]


def _contact_form(html: str) -> str:
    return re.search(r"<form[^>]*data-gwa-lead-form.*?</form>", html, re.S).group(0)


# --- Spanish chrome and per-page SEO -----------------------------------------------------------------


@pytest.mark.parametrize("build", ["canonical", "preview"])
@pytest.mark.parametrize("path", [*PAGES, "404.html"])
def test_every_page_is_spanish_with_a_title_description_and_one_h1(builds, build, path):
    html = _text(builds, build, path)

    assert re.search(r'<html lang="es"[\s>]', html)
    assert re.search(r"<title>[^<\s][^<]*</title>", _head(html))
    assert len(_meta(html, "name", "description")) == 1 and _meta(html, "name", "description")[0].strip()
    assert _meta(html, "property", "og:locale") == ["es_ES"]
    assert len(re.findall(r"<h1[\s>]", html)) == 1


@pytest.mark.parametrize("path", PAGES)
def test_with_a_verified_site_url_each_page_is_canonical_on_that_origin(builds, path):
    html = _text(builds, "canonical", path)
    expected = f"{ORIGIN}{CANONICAL_PATHS[path]}"

    assert _canonical(html) == [expected]
    assert _meta(html, "property", "og:url") == [expected]
    assert _meta(html, "name", "robots") == []


@pytest.mark.parametrize("path", PAGES)
def test_without_a_site_url_nothing_canonical_is_guessed(builds, path):
    html = _text(builds, "preview", path)

    assert _canonical(html) == []
    assert _meta(html, "property", "og:url") == []
    assert ORIGIN not in html


def test_local_business_json_ld_is_on_the_home_page_only(builds):
    home = _json_ld(_text(builds, "canonical", "index.html"))

    assert len(home) == 1
    assert home[0]["@context"] == "https://schema.org" and home[0]["@type"] == "LocalBusiness"
    assert home[0]["name"] == "Taller de Hilo"
    assert home[0]["url"] == f"{ORIGIN}/"
    assert "undefined" not in json.dumps(home[0]) and None not in home[0].values()
    for path in [*PAGES[1:], "404.html"]:
        assert _json_ld(_text(builds, "canonical", path)) == [], path


# --- robots.txt, sitemap.xml, 404 ---------------------------------------------------------------------


def test_robots_txt_allows_crawling_and_points_at_the_sitemap(builds):
    assert _text(builds, "canonical", "robots.txt") == f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n"


def test_without_a_site_url_robots_txt_names_no_sitemap_and_none_is_built(builds):
    assert _text(builds, "preview", "robots.txt") == "User-agent: *\nAllow: /\n"
    assert "sitemap.xml" not in builds["preview"].files


def test_the_sitemap_lists_every_page_once_at_its_canonical_url(builds):
    root = ET.fromstring(builds["canonical"].files["sitemap.xml"])
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    locs = [loc.text for loc in root.findall("s:url/s:loc", namespace)]

    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    assert locs == [f"{ORIGIN}{CANONICAL_PATHS[path]}" for path in PAGES]
    assert f"{ORIGIN}/404/" not in locs


@pytest.mark.parametrize("build", ["canonical", "preview"])
def test_the_404_page_is_never_indexed_or_canonical_and_links_home(builds, build):
    html = _text(builds, build, "404.html")

    assert _meta(html, "name", "robots") == ["noindex"]
    assert _canonical(html) == [] and _meta(html, "property", "og:url") == []
    assert re.search(r"<title>Página no encontrada · [^<]+</title>", html)
    assert re.search(r'<a href="/"[\s>]', html)


# --- Legal pages ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("build", ["canonical", "preview"])
def test_every_legal_link_on_the_home_page_resolves_to_a_built_page(builds, build):
    html = _text(builds, build, "index.html")
    links = set(re.findall(r'href="(/(?:aviso-legal|privacidad|cookies)/?)"', html))

    assert {link.rstrip("/") for link in links} == {"/aviso-legal", "/privacidad", "/cookies"}
    for link in links:
        assert f"{link.strip('/')}/index.html" in builds[build].files, link


def test_legacy_english_legal_paths_redirect_to_the_spanish_pages(builds):
    redirects = _text(builds, "canonical", "_redirects")

    assert "/privacy /privacidad/ 301" in redirects
    assert "/terms /aviso-legal/ 301" in redirects


# --- Contact form --------------------------------------------------------------------------------------


def test_the_consent_form_requires_email_message_and_a_labelled_consent_checkbox(builds):
    form = _contact_form(_text(builds, "canonical", "index.html"))

    assert re.search(r'<input id="contact-email" name="email" type="email" required[\s>]', form)
    assert re.search(r'<textarea id="contact-message" name="message" required[\s>]', form)
    assert re.search(r'<input id="contact-consent" type="checkbox" name="consent" required[\s>]', form)
    assert re.search(r'<label for="contact-consent"[^>]*>\s*Protección de datos', form)
    assert "He leído y acepto la política de privacidad." in form
    for field_id in re.findall(r'<(?:input|textarea|select) id="([\w-]+)"', form):
        assert f'<label for="{field_id}"' in form, field_id


def test_without_consent_required_the_message_is_optional_and_there_is_no_checkbox(builds):
    form = _contact_form(_text(builds, "preview", "index.html"))

    assert re.search(r'<textarea id="contact-message" name="message"(?! required)[^>]*>', form)
    assert 'name="consent"' not in form


@pytest.mark.parametrize("build", ["canonical", "preview"])
def test_the_first_layer_privacy_notice_links_to_the_privacy_policy(builds, build):
    html = _text(builds, build, "index.html")
    notice = re.search(r'<p class="block-contact__privacy"[^>]*>(.*?)</p>', html, re.S)

    assert notice is not None
    assert "Responsable:" in notice.group(1) and "Finalidad:" in notice.group(1)
    assert re.search(r'<a href="/privacidad/?"', notice.group(1))


@pytest.mark.parametrize("build", ["canonical", "preview"])
def test_the_honeypot_stays_out_of_reach_of_people_and_assistive_technology(builds, build):
    form = _contact_form(_text(builds, build, "index.html"))
    honeypot = re.search(r'<input type="text" name="hp_field"[^>]*>', form).group(0)

    assert 'tabindex="-1"' in honeypot and 'aria-hidden="true"' in honeypot and 'autocomplete="off"' in honeypot


# --- Local build isolation -----------------------------------------------------------------------------


def test_the_default_pages_dev_host_is_noindexed_only_when_a_custom_domain_is_canonical(builds):
    assert PAGES_DEV_NOINDEX in _text(builds, "canonical", "_headers")
    assert "pages.dev" not in _text(builds, "preview", "_headers")


@pytest.mark.parametrize("build", ["canonical", "preview"])
def test_a_local_build_only_ever_calls_the_local_api_and_names_no_production_host(builds, build):
    files = builds[build].files
    csp = re.search(r"Content-Security-Policy: ([^\n]+)", files["_headers"].decode()).group(1)

    assert re.search(r"connect-src 'self' http://localhost:8000(;|$)", csp)
    for path, data in files.items():
        if path.endswith((".html", ".txt", ".xml", "_headers", "_redirects", ".js", ".css")):
            text = data.decode("utf-8", "replace").replace(PAGES_DEV_NOINDEX, "")  # a host pattern, not a call
            assert not PRODUCTION_HOSTS.search(text), path
