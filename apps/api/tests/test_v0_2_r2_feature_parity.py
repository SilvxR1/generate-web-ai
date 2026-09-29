"""v0.2 R2 — GENERATIVE PLATFORM FEATURE PARITY.

    The AI controls presentation. The platform controls capabilities.
    No platform capability may require a predefined visual block.
    Platform contracts constrain behavior and truth, not composition.

A deterministic FREE-FORM fixture — deliberately unlike the legacy block
layout (lead form first, inside a <details> "letter"; services as a <dl> in
an <aside>; legal links scattered in prose; custom component names; no
legacy package, block or SiteConfig anywhere) — is rendered from
BusinessTruth, really built through the generative build (`npm ci` +
`astro build` + platform post-build injection), validated by the
PlatformContract, stored as a WebsiteArtifact, exercised in a real browser
(consent gating, lead submission) and its exact wire requests replayed
against the real public API in preview and production modes.

Deterministic fixtures only: no paid provider (no Anthropic, no Higgsfield),
no production. The fixture build needs npm registry access, like the
existing real-build tests; the browser test needs Chromium, like the
existing browser-QA tests.
"""

import html as html_lib
import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.creative.frontend_engine.browser_qa import _serve_directory, _write_files
from app.creative.frontend_engine.build import PLATFORM_CONSENT_FRAGMENT, build_generative_workspace
from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.prompts import build_system_prompt
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace, write_manifest
from app.db.models.business import Business
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.business_config.business_profile import ContactInfo, ServiceOffering
from app.domain.business_config.legal import LegalProfile
from app.domain.business_config.whatsapp import WhatsAppConfig
from app.domain.business_truth import BusinessTruth, derive_business_truth
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    BusinessStatus,
    BusinessVertical,
    ReviewSource,
)
from app.publishing.artifact_store import artifact_sha256, load_draft_artifact, store_draft_artifact
from app.qa.platform_contract import PlatformContractSeverity, validate_platform_contract
from app.storage import LocalStorageProvider
from app.storage.private import PrivateArtifactStorage
from tests import test_a8_real_draft_preview as _preview_tests

BUSINESS_ID = uuid.UUID("7e57f0e5-0000-4000-8000-00000000f00d")
API = "https://api.example.com"
PREVIEW_ORIGIN = _preview_tests.PREVIEW_ORIGIN
public_client = _preview_tests.public_client  # the real public API with a recording email sender
_counts = _preview_tests._counts

_PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7"
LOGO_URL = f"{_PIXEL}#logo"
PHOTO_URL = f"{_PIXEL}#photo"
GENERATED_URL = f"{_PIXEL}#generated"


class _Asset:
    def __init__(self, asset_id: str, kind, category, origin, url: str, alt: str | None = None) -> None:
        self.id = uuid.UUID(asset_id)
        self.kind, self.category, self.origin, self.url, self.alt_text = kind, category, origin, url, alt


class _Review:
    def __init__(self) -> None:
        self.id = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
        self.source = ReviewSource.MANUAL
        self.source_review_id = None
        self.author_name = "Ana"
        self.rating = 5
        self.body = "Nos reformaron la cocina en plazo."
        self.review_url = None
        self.published_at = None
        self.is_visible = True


def _business_config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(
            name="Nexo Reformas",
            slug="nexo-reformas",
            industry=BusinessVertical.HOME_RENOVATION,
            description="Reformas integrales en Valencia.",
            services=[
                ServiceOffering(id="cocinas", name="Cocinas", description="Reforma completa de cocinas."),
                ServiceOffering(id="banos", name="Baños", description="Reforma de baños."),
            ],
            contact=ContactInfo(email="hola@nexo.example", phone="+34 600 000 000"),
        ),
        legal_profile=LegalProfile(legal_name="Nexo Reformas S.L."),
        whatsapp=WhatsAppConfig(enabled=False),  # a phone exists, WhatsApp is NOT authoritative
    )


def _truth() -> BusinessTruth:
    assets = [
        _Asset(
            "00000000-0000-4000-8000-000000000001", AssetKind.LOGO, AssetCategory.LOGO, AssetOrigin.UPLOADED,
            LOGO_URL, "Logo de Nexo",
        ),
        _Asset(
            "00000000-0000-4000-8000-000000000002", AssetKind.IMAGE, AssetCategory.PROJECT, AssetOrigin.UPLOADED,
            PHOTO_URL, "Cocina reformada",
        ),
        _Asset(
            "00000000-0000-4000-8000-000000000003", AssetKind.IMAGE, AssetCategory.OTHER, AssetOrigin.GENERATED,
            GENERATED_URL, "Ilustración",
        ),
    ]
    return derive_business_truth(business_config=_business_config(), assets=assets, reviews=[_Review()])


def _t(value: str) -> str:
    return html_lib.escape(value, quote=True).replace("{", "&#123;").replace("}", "&#125;")


def freeform_manifest(truth: BusinessTruth) -> GeneratedProjectManifest:
    """A hand-authored, deterministic stand-in for AI output: every fact
    comes from BusinessTruth, and the composition is intentionally nothing
    like the legacy blocks."""
    logo = truth.logo
    assert logo is not None
    real_photo = next(a for a in truth.assets if a.is_real and a.kind is AssetKind.IMAGE)
    generated = next(a for a in truth.assets if not a.is_real)
    services = "\n".join(
        f'        <dt data-truth-service="{_t(s.id)}">{_t(s.name)}</dt><dd>{_t(s.description)}</dd>'
        for s in truth.services
    )
    reviews = "\n".join(
        f'      <blockquote data-truth-review="{r.id}"><p>{_t(r.body)}</p>'
        + (f"<cite>{_t(r.author_name)}</cite>" if r.author_name else "")
        + (f'<span aria-label="rating">{r.rating}/5</span>' if r.rating else "")
        + "</blockquote>"
        for r in truth.reviews
    )
    phone = truth.contact.phone or ""
    phone_href = "tel:" + re.sub(r"[^\d+]", "", phone)
    email = truth.contact.email or ""
    layout = """---
export interface Props { title: string; description: string; }
const { title, description } = Astro.props;
---
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <meta name="description" content={description} />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style is:global>
      :root { --gwa-consent-accent: #7a2e1f; --gwa-consent-radius: 0; }
      body { margin: 0; font-family: Georgia, serif; display: grid; grid-template-columns: 2fr 1fr; }
    </style>
  </head>
  <body>
    <slot />
    <script>import "../lib/platform-sdk";</script>
  </body>
</html>
"""
    atlas = f"""---
---
<aside class="atlas">
  <figure>
    <img src="{_t(logo.url)}" alt="{_t(logo.alt_text or truth.identity.name)}" data-truth-logo />
  </figure>
  <dl>
{services}
  </dl>
  <img src="{_t(generated.url)}" alt="" role="presentation" data-generated-illustration />
</aside>
"""
    index = f"""---
import Layout from "../layouts/Layout.astro";
import Atlas from "../components/Atlas.astro";
---
<Layout title="{_t(truth.identity.name)}" description="{_t(truth.description.description or '')}">
  <details id="write" open>
    <summary>Escríbenos una carta</summary>
    <form data-gwa-lead-form>
      <input name="name" aria-label="Nombre" />
      <input name="email" type="email" aria-label="Email" />
      <textarea name="message" aria-label="Mensaje"></textarea>
      <label><input type="checkbox" name="consent" value="true" /> Acepto la política</label>
      <button type="submit">Enviar carta</button>
    </form>
  </details>
  <main>
    <p class="kicker">{_t(truth.identity.name)}</p>
    <h1>{_t(truth.description.description or truth.identity.name)}</h1>
    <img src="{_t(real_photo.url)}" alt="{_t(real_photo.alt_text or '')}" data-truth-asset="{real_photo.id}" />
    <section id="voces">
{reviews}
    </section>
    <p>
      Llámanos al <a href="{phone_href}">{_t(phone)}</a>, escribe a
      <a href="mailto:{_t(email)}">{_t(email)}</a> o
      <a href="#write">déjanos una carta</a>. Consulta la <a href="/privacy">privacidad</a>, las
      <a href="/terms">condiciones</a> y las <a href="/cookies">cookies</a>
      (<button type="button" data-open-consent-preferences>ajustes de cookies</button>).
    </p>
  </main>
  <Atlas />
  <script>
    import {{ submitLead }} from "../lib/platform-sdk";
    const form = document.querySelector<HTMLFormElement>("form[data-gwa-lead-form]");
    form?.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const fields = Object.fromEntries(new FormData(form)) as Record<string, string>;
      const ok = await submitLead(fields);
      form.setAttribute("data-status", ok ? "sent" : "failed");
    }});
  </script>
</Layout>
"""
    return GeneratedProjectManifest(
        files=[
            GeneratedFile(path="src/layouts/Layout.astro", content=layout),
            GeneratedFile(path="src/components/Atlas.astro", content=atlas),
            GeneratedFile(path="src/pages/index.astro", content=index),
        ]
    )


@pytest.fixture(scope="module")
def built():
    """One real generative build of the free-form fixture for this module."""
    truth = _truth()
    manifest = freeform_manifest(truth)
    workspace = allocate_workspace()
    try:
        write_manifest(
            workspace,
            manifest,
            package_json=build_package_json(name="freeform-fixture", additional_dependencies=[]),
            astro_config=ASTRO_CONFIG,
            tsconfig=TSCONFIG,
        )
        for relative_path, content in build_legal_pages(truth).items():
            page = workspace / relative_path
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(content, encoding="utf-8")
        artifact = build_generative_workspace(workspace, business_id=str(BUSINESS_ID), api_base_url=API)
    finally:
        cleanup_workspace(workspace)
    return truth, manifest, artifact


def _html(artifact) -> dict[str, str]:
    return {p: c.decode("utf-8") for p, c in artifact.files.items() if p.endswith(".html")}


# --- Renderer independence ----------------------------------------------------


def test_free_form_fixture_uses_no_legacy_block_or_site_config(built):
    _, manifest, _ = built
    source = "\n".join(f.content for f in manifest.files)
    for legacy in (
        "@generate-web-ai/blocks", "@generate-web-ai/renderer", "@generate-web-ai/site-config",
        "SiteConfig", "HeroBlock", "BlockRenderer", "Contact.astro", "site-header",
    ):
        assert legacy not in source, legacy
    # Unusual composition: the lead form comes before the heading, services are a <dl>.
    index = next(f.content for f in manifest.files if f.path == "src/pages/index.astro")
    assert index.index("data-gwa-lead-form") < index.index("<h1>")
    assert "<dl>" in next(f.content for f in manifest.files if f.path == "src/components/Atlas.astro")


def test_free_form_build_passes_the_platform_contract(built):
    _, _, artifact = built
    result = validate_platform_contract(artifact.files, business_config=_business_config())
    blocking = [f"{f.rule}: {f.message}" for f in result.findings if f.severity is PlatformContractSeverity.BLOCKING]
    assert blocking == []
    assert result.version == "1.1.0"


def test_every_page_gets_the_platform_consent_banner_and_safe_runtime_config(built):
    _, _, artifact = built
    pages = _html(artifact)
    assert set(pages) >= {"index.html", "privacy/index.html", "terms/index.html", "cookies/index.html"}
    for path, page in pages.items():
        assert page.count(PLATFORM_CONSENT_FRAGMENT) == 1, path
        [raw] = re.findall(r'<script type="application/json" id="platform-config">(.*?)</script>', page)
        assert json.loads(raw) == {"businessId": str(BUSINESS_ID), "apiBaseUrl": API}, path  # nothing secret


def test_business_truth_facts_and_assets_render_and_nothing_unauthoritative_appears(built):
    truth, _, artifact = built
    pages = _html(artifact)
    page = pages["index.html"]
    assert truth.identity.name in page
    for service in truth.services:
        assert html_lib.escape(service.name) in page or service.name in page
    assert 'href="tel:+34600000000"' in page and 'href="mailto:hola@nexo.example"' in page
    assert "wa.me" not in page  # a phone number never implies WhatsApp
    assert "data-truth-logo" in page and "#logo" in page  # the real logo, by truth
    assert "#photo" in page  # the real photo
    assert "Nos reformaron la cocina en plazo." in page and "<cite>Ana</cite>" in page  # the one real review
    assert page.count("data-truth-review") == len(truth.reviews) == 1  # nothing fabricated
    assert "Legal name: Nexo Reformas S.L." in pages["privacy/index.html"]


def test_free_form_build_becomes_an_immutable_website_artifact(built, tmp_path):
    _, _, artifact = built
    storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private"))
    draft_id = uuid.uuid4()
    stored = store_draft_artifact(
        storage, tenant_id=uuid.uuid4(), business_id=BUSINESS_ID, draft_id=draft_id, artifact=artifact
    )
    reloaded = load_draft_artifact(
        storage, storage_key=stored.storage_key, expected_sha256=stored.sha256, draft_id=draft_id
    )
    assert artifact_sha256(reloaded) == stored.sha256 == artifact_sha256(artifact)


# --- Real browser: consent gating, lead submission -----------------------------


def test_real_browser_consent_gates_analytics_and_the_lead_reaches_the_platform_endpoint(built, tmp_path):
    from app.creative.frontend_engine.browser_qa import check_browser_qa_availability

    available, reason = check_browser_qa_availability()
    if not available:
        pytest.skip(f"Chromium unavailable: {reason}")
    from playwright.sync_api import sync_playwright

    _, _, artifact = built
    root = tmp_path / "site"
    _write_files(root, artifact.files)
    requests: list[dict] = []

    def _intercept(route):
        request = route.request
        requests.append({"url": request.url, "body": json.loads(request.post_data or "null")})
        route.fulfill(status=201, content_type="application/json", body="{}")

    with _serve_directory(root) as port, sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.route(f"{API}/**", _intercept)
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")

            assert page.is_visible("#gwa-consent-banner")  # platform banner, no stored choice yet
            assert not [r for r in requests if r["url"].endswith("/events")]  # page_view held until consent

            page.fill("input[name=name]", "Visitante")
            page.fill("input[name=email]", "visitante@example.com")
            page.fill("textarea[name=message]", "Quiero reformar mi baño")
            page.check("input[name=consent]")
            page.click("form[data-gwa-lead-form] button[type=submit]")
            page.wait_for_selector("form[data-status=sent]")
            [lead] = [r for r in requests if r["url"].endswith("/leads")]
            assert lead["url"] == f"{API}/public/businesses/{BUSINESS_ID}/leads"  # platform attribution
            assert lead["body"]["name"] == "Visitante" and lead["body"]["consent"] is True
            assert not [r for r in requests if r["url"].endswith("/events")]  # still no analytics

            page.click("#gwa-consent-accept")
            page.wait_for_timeout(300)
            events = [r["body"]["event_type"] for r in requests if r["url"].endswith("/events")]
            assert "page_view" in events and "lead_submitted" in events  # released only after consent
            assert not page.is_visible("#gwa-consent-banner")

            page.reload(wait_until="networkidle")
            assert not page.is_visible("#gwa-consent-banner")  # the choice is remembered
            page.click("[data-open-consent-preferences]")
            assert page.is_visible("#gwa-consent-banner")  # reopenable from the design's own control
        finally:
            browser.close()


# --- Preview suppression is platform-enforced ------------------------------------


def test_the_fixtures_wire_requests_are_suppressed_in_preview_and_recorded_in_production(
    public_client: TestClient, session, tenant
):
    business = Business(
        id=BUSINESS_ID,
        tenant_id=tenant.id,
        name="Nexo Reformas",
        slug="nexo-reformas",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="x",
        status=BusinessStatus.DRAFT,
    )
    session.add(business)
    session.flush()
    # Exactly the wire contract the platform SDK sends (see the browser test).
    lead = {
        "name": "Visitante", "email": "visitante@example.com", "message": "Quiero reformar mi baño",
        "consent": True, "company_website": "", "source_url": "https://site.example/",
    }
    event = {"event_type": "page_view", "source_page": "/"}
    leads_url = f"/public/businesses/{BUSINESS_ID}/leads"
    events_url = f"/public/businesses/{BUSINESS_ID}/events"

    before = _counts(session, business)
    sent_before = len(public_client.sender.sent)
    preview_lead = public_client.post(leads_url, json=lead, headers={"Origin": PREVIEW_ORIGIN})
    preview_event = public_client.post(events_url, json=event, headers={"Origin": PREVIEW_ORIGIN})
    assert preview_lead.status_code == 201 and preview_event.status_code == 201  # the site behaves normally
    assert _counts(session, business) == before  # 0 leads, 0 notifications, 0 events
    assert len(public_client.sender.sent) == sent_before  # 0 emails

    production = public_client.post(leads_url, json=lead, headers={"Origin": "https://nexo.example"})
    assert production.status_code == 201
    assert _counts(session, business)[0] == before[0] + 1  # the same request is a real lead in production


# --- Prompt: behavior, not layout ----------------------------------------------


def test_prompt_grants_visual_freedom_and_describes_behavior_only():
    system = build_system_prompt()
    assert "You are free to design the visual composition" in system
    assert "describe BEHAVIOR, not layout" in system
    assert "Do NOT build a consent banner" in system
    assert "a footer with links" not in system  # no placement is prescribed
    assert "visible cookie-consent banner UI" not in system


# --- New renderer-independent contract rules --------------------------------------


def _rules(files: dict[str, bytes], config: BusinessConfig | None = None) -> set[str]:
    result = validate_platform_contract(files, business_config=config or _business_config())
    return {f.rule for f in result.findings if f.severity is PlatformContractSeverity.BLOCKING}


def test_contract_rules_catch_capability_regressions_without_constraining_layout(built):
    _, _, artifact = built
    files = dict(artifact.files)
    index = files["index.html"].decode()

    def with_index(new_index: str) -> dict[str, bytes]:
        return {**files, "index.html": new_index.encode()}

    assert _rules(files) == set()
    no_banner = index.replace(PLATFORM_CONSENT_FRAGMENT, "")
    assert "missing_consent_controls" in _rules(with_index(no_banner))
    hidden = index.replace("</head>", "<style>#gwa-consent-banner{display:none!important}</style></head>")
    assert "consent_banner_overridden" in _rules(with_index(hidden))
    unlinked = index.replace('href="/cookies"', 'href="/cookie-policy-elsewhere"')
    assert {"legal_page_unlinked", "broken_internal_link"} <= _rules(with_index(unlinked))
    external = index.replace("</head>", '<script src="https://cdn.example.com/x.js"></script></head>')
    assert "external_script_source" in _rules(with_index(external))
    config_json = json.dumps({"businessId": str(BUSINESS_ID), "apiBaseUrl": API})
    leaky_json = json.dumps({"businessId": str(BUSINESS_ID), "apiBaseUrl": API, "apiKey": "x"})
    assert config_json in index
    assert "unsafe_runtime_config" in _rules(with_index(index.replace(config_json, leaky_json)))
    whatsapp = index.replace("</main>", '<a href="https://wa.me/34600000000">WhatsApp</a></main>')
    assert "unauthorized_whatsapp_link" in _rules(with_index(whatsapp))  # a phone is not WhatsApp
    enabled = _business_config().model_copy(
        update={"whatsapp": WhatsAppConfig(enabled=True, phone_number="+34 600 000 000")}
    )
    assert "unauthorized_whatsapp_link" not in _rules(with_index(whatsapp), enabled)
    # Recomposing the page (new classes, different order) changes nothing.
    recomposed = index.replace('class="kicker"', 'class="entirely-different"')
    assert _rules(with_index(recomposed)) == set()
