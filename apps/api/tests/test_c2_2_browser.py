"""C2.2: browser-level checks of C2.1's public site, on REAL local builds.

The two fictional builds from test_c2_2_built_site.py are served from
127.0.0.1 (app.creative.frontend_engine.browser_qa's own server, which also
applies the artifact's `_headers`, CSP included) and driven with Playwright's
Chromium. Nothing leaves the machine:

- the page may load the local site; every other request is answered by this
  test or aborted, and an aborted request fails the test;
- the fixtures' fictional image URLs (cdn.example.com) get a 1x1 PNG;
- the lead endpoint and the analytics beacon (http://localhost:8000, the
  local build's API origin) are answered by this test and recorded, so the
  running local API is never called.

axe-core is not a project dependency. The accessibility test uses a local
copy (GWA_AXE_CORE_PATH, or the first axe.min.js in the bun/npm caches) and
is skipped, never silently passed, when none exists.
"""

import base64
import glob
import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.creative.frontend_engine.browser_qa import _serve_directory, _write_files, check_browser_qa_availability
from app.publishing import build as build_module
from tests.test_c2_2_built_site import ORIGIN, _site

AVAILABLE, UNAVAILABLE_REASON = check_browser_qa_availability()
pytestmark = pytest.mark.skipif(not AVAILABLE, reason=f"Playwright/Chromium unavailable: {UNAVAILABLE_REASON}")

VIEWPORTS = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (390, 844), "small": (320, 568)}
PAGES = ("/", "/aviso-legal/", "/privacidad/", "/cookies/", "/404.html")
LOCAL_API = "http://localhost:8000"
BUSINESS_ID = "00000000-0000-4000-8000-000000000001"
LEADS_URL = f"{LOCAL_API}/public/businesses/{BUSINESS_ID}/leads"
EVENTS_URL = f"{LOCAL_API}/public/businesses/{BUSINESS_ID}/events"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
SUCCESS = "Gracias. Hemos recibido tu mensaje y te responderemos en breve."
FAILURE = "No hemos podido enviar tu mensaje. Comprueba tu conexión e inténtalo de nuevo."


@dataclass
class Traffic:
    """Everything the page asked for beyond the local site."""

    leads: list[dict] = field(default_factory=list)
    events: int = 0
    stubbed_images: int = 0
    unexpected: list[str] = field(default_factory=list)
    # How to answer each lead POST, in order (then 201): an HTTP status, "abort:<error>" (the request
    # fails on the network), "hang" (never answered), or a callable(route, payload) that answers it.
    lead_statuses: list = field(default_factory=list)
    hung: list = field(default_factory=list)


@pytest.fixture(scope="module")
def sites(tmp_path_factory) -> Iterator[dict[str, str]]:
    """Both fictional builds, each served on its own 127.0.0.1 port."""
    builds = {
        "canonical": build_module.build_site(_site("handmade_shop", site_url=ORIGIN, consent=True)),
        "preview": build_module.build_site(_site("renovation", site_url=None, consent=False)),
    }
    with ExitStack() as stack:
        urls = {}
        for name, artifact in builds.items():
            root = tmp_path_factory.mktemp(name)
            _write_files(root, artifact.files)
            urls[name] = f"http://127.0.0.1:{stack.enter_context(_serve_directory(root))}"
        yield urls


@pytest.fixture(scope="module")
def browser() -> Iterator:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        yield chromium
        chromium.close()


def _router(base_url: str, traffic: Traffic) -> Callable:
    def handle(route) -> None:
        request = route.request
        url = request.url
        if url.startswith(base_url + "/") or url == base_url:
            route.continue_()
        elif url.startswith("https://cdn.example.com/"):
            traffic.stubbed_images += 1
            route.fulfill(status=200, body=PNG_1X1, headers={"content-type": "image/png"})
        elif url == LEADS_URL and request.method == "OPTIONS":
            route.fulfill(status=204, headers=_cors())
        elif url == LEADS_URL and request.method == "POST":
            payload = json.loads(request.post_data or "{}")
            traffic.leads.append(payload)
            answer = traffic.lead_statuses.pop(0) if traffic.lead_statuses else 201
            if callable(answer):
                answer(route, payload)
            elif answer == "hang":
                traffic.hung.append(route)
            elif isinstance(answer, str) and answer.startswith("abort:"):
                route.abort(answer.removeprefix("abort:"))
            else:
                route.fulfill(status=answer, body=json.dumps({"received": True}), headers=_cors())
        elif url == EVENTS_URL:
            traffic.events += 1
            route.fulfill(status=202 if request.method == "POST" else 204, body="{}", headers=_cors())
        else:
            traffic.unexpected.append(f"{request.method} {url[:200]}")
            route.abort()

    return handle


def _cors() -> dict[str, str]:
    return {
        "content-type": "application/json",
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "content-type",
        "access-control-allow-methods": "POST, OPTIONS",
    }


@pytest.fixture()
def open_page(browser, sites) -> Iterator[Callable]:
    """open_page(site, path, viewport=..., bypass_csp=False, reduced_motion=False)
    -> (page, traffic, console_errors). Every page starts with a fresh context
    (empty localStorage), so the consent banner shows as on a first visit."""
    contexts: list = []
    traffics: list[Traffic] = []

    def _open(
        site: str,
        path: str = "/",
        *,
        viewport: str = "desktop",
        bypass_csp: bool = False,
        reduced_motion: bool = False,
        clock: bool = False,
    ):
        width, height = VIEWPORTS[viewport]
        context = browser.new_context(
            viewport={"width": width, "height": height},
            bypass_csp=bypass_csp,
            reduced_motion="reduce" if reduced_motion else "no-preference",
        )
        contexts.append(context)
        traffic = Traffic()
        traffics.append(traffic)
        context.route("**/*", _router(sites[site], traffic))
        page = context.new_page()
        errors: list[str] = []
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append(str(error)))
        if clock:
            page.clock.install()  # the page's timers then advance only when the test says so
        page.goto(sites[site] + path, wait_until="load")
        return page, traffic, errors

    yield _open
    for route in [route for traffic in traffics for route in traffic.hung]:
        route.abort()
    for context in contexts:
        context.close()
    unexpected = [request for traffic in traffics for request in traffic.unexpected]
    assert unexpected == [], f"the page tried to reach something other than the local site: {unexpected}"


def _dismiss_consent_banner(page) -> None:
    banner = page.locator("#gwa-consent-banner")
    if banner.is_visible():
        banner.get_by_role("button", name="Rechazar opcionales").click()
        assert banner.is_hidden()


def _wait_for_state(page, state: str) -> None:
    # Playwright's expect polls without eval, which the site's CSP (correctly) forbids.
    from playwright.sync_api import expect

    expect(page.locator("form[data-gwa-lead-form]")).to_have_attribute("data-lead-submission-state", state)


def _fill_canonical_form(page, *, consent: bool = True) -> None:
    page.fill("#contact-name", "Lucía Prueba")
    page.fill("#contact-email", "lucia@example.com")
    page.fill("#contact-message", "Hola, quería información sobre un encargo.")
    if consent:
        page.check("#contact-consent")


# --- Every page, every viewport -----------------------------------------------------------------------


@pytest.mark.parametrize("viewport", VIEWPORTS)
@pytest.mark.parametrize("site", ["canonical", "preview"])
def test_every_page_renders_without_errors_overflow_or_broken_images(open_page, site, viewport):
    for path in PAGES:
        page, _traffic, errors = open_page(site, path, viewport=viewport)

        assert errors == [], (path, errors)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (path, "overflow")
        broken = page.evaluate("[...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.src)")
        assert broken == [], (path, broken)
        assert page.locator("h1").count() == 1, path


@pytest.mark.parametrize("site", ["canonical", "preview"])
def test_every_image_has_alternative_text_or_is_marked_decorative(open_page, site):
    page, _traffic, _errors = open_page(site)

    missing = page.evaluate(
        "[...document.images].filter(i => !i.hasAttribute('alt') && i.getAttribute('role') !== 'presentation')"
        ".map(i => i.src)"
    )
    assert missing == []


# --- Navigation ----------------------------------------------------------------------------------------


def test_the_mobile_menu_opens_by_keyboard_and_reaches_every_section(open_page):
    page, _traffic, _errors = open_page("canonical", viewport="mobile")
    _dismiss_consent_banner(page)
    inline = page.locator(".site-nav__list")
    menu = page.locator(".site-nav__menu")

    assert inline.is_hidden() and menu.is_visible()
    links = menu.locator("a")
    assert links.first.is_hidden()
    menu.locator("summary").focus()
    page.keyboard.press("Enter")
    assert links.first.is_visible()
    for href in links.evaluate_all("links => links.map(a => a.getAttribute('href'))"):
        assert href.startswith("#") and page.locator(href).count() == 1, href


def test_on_desktop_the_inline_navigation_replaces_the_menu(open_page):
    page, _traffic, _errors = open_page("canonical", viewport="desktop")

    assert page.locator(".site-nav__list").is_visible()
    assert page.locator(".site-nav__menu").is_hidden()


@pytest.mark.parametrize("viewport", ["desktop", "mobile"])
def test_keyboard_focus_is_always_visible_and_never_reaches_the_honeypot(open_page, viewport):
    page, _traffic, _errors = open_page("canonical", viewport=viewport)
    _dismiss_consent_banner(page)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    seen = []
    for _ in range(80):
        page.keyboard.press("Tab")
        focused = page.evaluate(
            """() => {
              const el = document.activeElement;
              if (!el || el === document.body) return null;
              if (el.dataset.c22Focused) return {repeat: true};  // wrapped around: every stop visited
              el.dataset.c22Focused = "1";
              const style = getComputedStyle(el);
              const box = el.getBoundingClientRect();
              return {
                tag: el.tagName.toLowerCase(), name: el.getAttribute('name'), id: el.id,
                text: (el.textContent || '').trim().slice(0, 40),
                visible: box.width > 0 && box.height > 0 && style.visibility !== 'hidden',
                indicator: (style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0)
                  || style.boxShadow !== 'none',
              };
            }"""
        )
        if focused is None or focused.get("repeat"):
            break
        seen.append(focused)

    assert len(seen) >= 5, seen
    assert all(item["name"] != "hp_field" for item in seen)
    without_indicator = [item for item in seen if not (item["visible"] and item["indicator"])]
    assert without_indicator == [], without_indicator


# --- Contact form --------------------------------------------------------------------------------------


def test_an_empty_or_invalid_form_is_never_sent(open_page):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    submit = page.locator("button.block-contact__submit")

    submit.click()
    assert page.evaluate("document.activeElement.id") == "contact-name"
    assert page.evaluate("document.getElementById('contact-name').validity.valueMissing")

    _fill_canonical_form(page)
    page.fill("#contact-email", "no-es-un-correo")
    submit.click()
    assert page.evaluate("document.getElementById('contact-email').validity.typeMismatch")
    assert traffic.leads == []


def test_consent_is_required_before_anything_is_sent(open_page):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    _fill_canonical_form(page, consent=False)

    page.locator("button.block-contact__submit").click()

    assert page.evaluate("document.getElementById('contact-consent').validity.valueMissing")
    assert traffic.leads == []


def test_a_valid_submission_is_sent_once_with_consent_and_confirmed(open_page):
    page, traffic, errors = open_page("canonical")
    _dismiss_consent_banner(page)
    _fill_canonical_form(page)

    # Two submits in the same task (a double click, Enter held down).
    page.evaluate(
        "() => { const f = document.querySelector('form[data-gwa-lead-form]'); f.requestSubmit(); f.requestSubmit(); }"
    )
    status = page.locator(".block-contact__status")
    status.wait_for(state="visible")

    assert status.inner_text() == SUCCESS
    assert page.locator("#contact-name").is_disabled()
    assert len(traffic.leads) == 1
    lead = traffic.leads[0]
    assert lead["name"] == "Lucía Prueba" and lead["email"] == "lucia@example.com"
    assert lead["message"] == "Hola, quería información sobre un encargo."
    assert lead["consent"] is True
    assert lead["company_website"] == "" and lead["rendered_at"]
    assert UUID_V4.match(lead["submission_id"])
    assert lead["source_url"] == f"{ORIGIN}/"  # C2.3: the page's canonical URL, not the serving host
    assert not {"tenant_id", "business_id", "tenantId", "businessId"} & set(lead)
    assert errors == []


def test_a_failed_send_keeps_the_values_and_a_retry_succeeds(open_page):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    traffic.lead_statuses = [503]
    _fill_canonical_form(page)
    submit = page.locator("button.block-contact__submit")
    status = page.locator(".block-contact__status")

    submit.click()
    _wait_for_state(page, "error")
    assert status.inner_text() == FAILURE
    assert page.input_value("#contact-message") == "Hola, quería información sobre un encargo."
    assert submit.is_enabled()

    submit.click()
    _wait_for_state(page, "submitted")
    assert status.inner_text() == SUCCESS
    assert len(traffic.leads) == 2


# --- C2.3: submission_id lifecycle and source_url ------------------------------------------------------


@pytest.mark.parametrize(
    "first_answer",
    [503, "abort:timedout", "abort:connectionreset", "abort:internetdisconnected"],
    ids=["ambiguous-503", "network-timeout", "connection-reset", "offline"],
)
def test_a_retry_after_a_failure_reuses_the_same_submission_id(open_page, first_answer):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    traffic.lead_statuses = [first_answer]
    _fill_canonical_form(page)
    submit = page.locator("button.block-contact__submit")

    submit.click()
    _wait_for_state(page, "error")
    assert page.locator(".block-contact__status").inner_text() == FAILURE
    submit.click()
    _wait_for_state(page, "submitted")

    ids = [lead["submission_id"] for lead in traffic.leads]
    assert len(ids) == 2 and UUID_V4.match(ids[0]) and ids[1] == ids[0]


def test_a_request_with_no_answer_times_out_and_its_retry_reuses_the_id(open_page):
    page, traffic, _errors = open_page("canonical", clock=True)
    _dismiss_consent_banner(page)
    traffic.lead_statuses = ["hang"]
    _fill_canonical_form(page)
    submit = page.locator("button.block-contact__submit")

    submit.click()
    _wait_for_state(page, "submitting")
    assert submit.is_disabled()
    page.clock.run_for(20_000)  # LeadSubmission.astro's REQUEST_TIMEOUT_MS
    _wait_for_state(page, "error")
    assert submit.is_enabled() and page.input_value("#contact-name") == "Lucía Prueba"
    submit.click()
    _wait_for_state(page, "submitted")

    assert len(traffic.leads) == 2 and traffic.leads[1]["submission_id"] == traffic.leads[0]["submission_id"]


def test_changed_content_after_a_failure_is_a_new_submission_with_a_new_id(open_page):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    traffic.lead_statuses = [503]
    _fill_canonical_form(page)
    submit = page.locator("button.block-contact__submit")
    submit.click()
    _wait_for_state(page, "error")

    page.fill("#contact-message", "En realidad era otra consulta.")
    submit.click()
    _wait_for_state(page, "submitted")

    first, second = (lead["submission_id"] for lead in traffic.leads)
    assert UUID_V4.match(first) and UUID_V4.match(second) and first != second


def test_a_new_visit_is_a_new_submission_with_a_new_id(open_page):
    ids = []
    for _ in range(2):
        page, traffic, _errors = open_page("canonical")
        _dismiss_consent_banner(page)
        _fill_canonical_form(page)
        page.locator("button.block-contact__submit").click()
        _wait_for_state(page, "submitted")
        ids += [lead["submission_id"] for lead in traffic.leads]

    assert len(ids) == 2 and ids[0] != ids[1]


def test_a_server_validation_error_keeps_the_form_and_its_retry_reuses_the_id(open_page):
    page, traffic, _errors = open_page("canonical")
    _dismiss_consent_banner(page)
    traffic.lead_statuses = [422]
    _fill_canonical_form(page)
    submit = page.locator("button.block-contact__submit")

    submit.click()
    _wait_for_state(page, "error")

    assert page.locator(".block-contact__status").inner_text() == FAILURE
    assert submit.is_enabled() and page.is_checked("#contact-consent")
    assert page.input_value("#contact-email") == "lucia@example.com"
    submit.click()
    _wait_for_state(page, "submitted")
    assert traffic.leads[1]["submission_id"] == traffic.leads[0]["submission_id"]


def test_source_url_is_the_page_without_its_query_or_fragment(open_page, sites):
    page, traffic, _errors = open_page("preview", "/?utm_source=campana&token=secreto#contact")
    _dismiss_consent_banner(page)
    page.fill("#contact-name", "Jordi Prueba")
    page.fill("#contact-phone", "+34 600 000 000")
    page.select_option("#contact-service", index=1)

    page.locator("button.block-contact__submit").click()
    _wait_for_state(page, "submitted")

    assert traffic.leads[0]["source_url"] == f"{sites['preview']}/"  # no canonical on a preview build


def test_a_stored_lead_whose_response_is_lost_is_stored_once_by_the_real_api(open_page, session):
    """The real public lead route (app.routers.public, in-memory SQLite) answers
    the page: the first request IS stored but its response never reaches the
    browser; the visitor's retry carries the same submission_id, and the API
    answers it without a second lead."""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.db.models.business import Business
    from app.db.models.lead import Lead
    from app.db.models.tenant import Tenant
    from app.dependencies import get_rate_limiter, get_session
    from app.domain.enums import BusinessStatus, BusinessVertical
    from app.main import app
    from app.security.rate_limit import InMemoryRateLimiter

    tenant = Tenant(name="Taller de Hilo (ficticio)")
    session.add(tenant)
    session.flush()
    session.add(
        Business(
            id=uuid.UUID(BUSINESS_ID),
            tenant_id=tenant.id,
            name="Taller de Hilo",
            slug="taller-de-hilo",
            vertical=BusinessVertical.ECOMMERCE,
            raw_description="Negocio ficticio de prueba.",
            status=BusinessStatus.ACTIVE,
        )
    )
    session.flush()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    api = TestClient(app)

    def to_api(*, lose_response: bool) -> Callable:
        def answer(route, payload) -> None:
            response = api.post(f"/public/businesses/{BUSINESS_ID}/leads", json=payload)
            assert response.status_code == 201, response.text
            if lose_response:
                route.abort("connectionreset")
            else:
                route.fulfill(status=response.status_code, body=response.content, headers=_cors())

        return answer

    try:
        page, traffic, _errors = open_page("canonical")
        _dismiss_consent_banner(page)
        traffic.lead_statuses = [to_api(lose_response=True), to_api(lose_response=False)]
        _fill_canonical_form(page)
        page.wait_for_timeout(2_100)  # a real visitor's pace: faster is dropped as spam (app.leads.spam)
        submit = page.locator("button.block-contact__submit")
        submit.click()
        _wait_for_state(page, "error")
        submit.click()
        _wait_for_state(page, "submitted")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)

    leads = session.scalars(select(Lead).where(Lead.business_id == uuid.UUID(BUSINESS_ID))).all()
    assert len(traffic.leads) == 2
    assert len(leads) == 1
    assert str(leads[0].client_submission_id) == traffic.leads[0]["submission_id"]
    assert leads[0].source_url == f"{ORIGIN}/" and leads[0].consent_given is True
    assert leads[0].message == "Hola, quería información sobre un encargo."


def test_the_preview_form_without_consent_or_message_is_sent(open_page):
    page, traffic, _errors = open_page("preview", viewport="mobile")
    _dismiss_consent_banner(page)
    page.fill("#contact-name", "Jordi Prueba")
    page.fill("#contact-phone", "+34 600 000 000")
    page.select_option("#contact-service", index=1)

    page.locator("button.block-contact__submit").click()
    page.locator(".block-contact__status").wait_for(state="visible")

    assert len(traffic.leads) == 1
    assert traffic.leads[0]["consent"] is False and "message" not in traffic.leads[0]


# --- Consent banner ------------------------------------------------------------------------------------


def test_the_consent_choice_is_remembered_and_can_be_reopened_from_the_footer(open_page):
    page, _traffic, _errors = open_page("canonical", viewport="mobile")
    banner = page.locator("#gwa-consent-banner")
    assert banner.is_visible()

    banner.get_by_role("button", name="Rechazar opcionales").focus()
    page.keyboard.press("Enter")
    assert banner.is_hidden()
    page.reload()
    assert banner.is_hidden()

    page.locator("[data-open-consent-preferences]").click()
    assert banner.is_visible()


# --- Accessibility (axe-core) --------------------------------------------------------------------------


def _axe_path() -> str | None:
    explicit = os.environ.get("GWA_AXE_CORE_PATH")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    home = os.path.expanduser("~")
    for pattern in (
        f"{home}/.bun/install/cache/axe-core@*/axe.min.js",
        f"{home}/.npm/_npx/*/node_modules/axe-core/axe.min.js",
    ):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return None


AXE_RESULTS: dict[tuple[str, str, str], list[dict]] = {}


@pytest.mark.parametrize("viewport", ["desktop", "mobile"])
@pytest.mark.parametrize("site", ["canonical", "preview"])
def test_axe_finds_no_serious_or_critical_wcag_violations(open_page, site, viewport):
    axe = _axe_path()
    if axe is None:
        pytest.skip("no local axe-core copy (set GWA_AXE_CORE_PATH); never installed by this suite")
    serious = []
    for path in PAGES:
        # The artifact's CSP (correctly) refuses injected scripts; bypass it for
        # the audit only. Every other test runs under the real policy. Reduced
        # motion audits the settled page: with motion on, axe measures
        # scroll-reveal sections mid-fade (blended, lighter colours) and reports
        # contrast failures no visitor sees once a section has appeared.
        page, _traffic, _errors = open_page(site, path, viewport=viewport, bypass_csp=True, reduced_motion=True)
        page.add_script_tag(path=axe)
        result = page.evaluate(
            "() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})"
        )
        violations = [
            {"id": v["id"], "impact": v["impact"], "nodes": [n["target"] for n in v["nodes"]][:5]}
            for v in result["violations"]
        ]
        AXE_RESULTS[(site, viewport, path)] = violations
        serious += [(path, v) for v in violations if v["impact"] in ("serious", "critical")]
    report = os.environ.get("GWA_C22_AXE_REPORT")
    if report:
        Path(report).write_text(json.dumps({"|".join(k): v for k, v in AXE_RESULTS.items()}, indent=1))
    assert serious == [], serious


def test_no_request_ever_left_for_a_non_local_host(open_page):
    """The router fails any test whose page asked for anything else; this
    one checks that the fixtures' images were indeed answered locally."""
    page, traffic, _errors = open_page("canonical")
    page.wait_for_load_state("networkidle")

    assert traffic.stubbed_images >= 1
    assert re.match(r"http://127\.0\.0\.1:\d+$", page.evaluate("location.origin"))
