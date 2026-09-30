"""H2 end-to-end QA for an artifact produced by the source-adapter pipeline
(scripts/h2_source_adapter.py), against the REAL GWA API (local,
throwaway database) — nothing leaves this machine except the page's own
allowed font requests.

    uv run python scripts/h2_e2e_qa.py --fixture nexo-reformas --work-root /tmp/gwa-h2/nexo \
        --offsets /tmp/gwa-higgsfield-portability/visual/report.json --baseline /tmp/gwa-h1/run8/qa
    uv run python scripts/h2_e2e_qa.py --fixture lumen-physio --work-root /tmp/gwa-h2/lumen

Generic by construction: the form is filled and the stored lead is checked
from the plan's FormMapping; legal titles come from the adapted legal
content; CSP/origins from the plan. A fixture PROFILE holds only what a
tester states about that design (its title, success/failure texts, fonts,
and Nexo's scroll-film checks).

Isolation: before `app` is imported, the process moves into
<work-root>/e2e (so no `.env` is read), points DATABASE_URL at a fresh
SQLite file there and removes every provider credential/URL from its own
environment; it REFUSES to run unless all of them are unset.
Writes <work-root>/qa/qa-report.json and screenshots.
"""

import argparse
import os
import sys
from pathlib import Path

_PARSER = argparse.ArgumentParser()
_PARSER.add_argument("--fixture", choices=("nexo-reformas", "lumen-physio"), required=True)
_PARSER.add_argument("--work-root", type=Path, required=True)
_PARSER.add_argument("--offsets", type=Path, help="spike report.json with the screenshot offsets (Nexo)")
_PARSER.add_argument("--baseline", type=Path, help="directory of baseline screenshots adapted-<vp>-NN.png")
ARGS = _PARSER.parse_args()
WORK_ROOT = ARGS.work_root.resolve()
E2E_DIR = WORK_ROOT / "e2e"
E2E_DIR.mkdir(parents=True, exist_ok=True)
API_ROOT = Path(__file__).resolve().parent.parent
_PROVIDER_ENV = (
    "CREDENTIAL_ENCRYPTION_KEY N8N_BASE_URL N8N_API_KEY ANTHROPIC_API_KEY GENERATION_WORKER_TOKEN_SHA256 "
    "GENERATION_WORKER_SIGNING_KEY INTERNAL_AUTOMATION_TOKEN CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_TOKEN SMTP_HOST "
    "SMTP_PASSWORD RESEND_API_KEY HIGGSFIELD_API_KEY HIGGSFIELD_BASE_URL HIGGSFIELD_API_KEY_ID "
    "HIGGSFIELD_API_KEY_SECRET HIGGSFIELD_API_KEY_NAME GOOGLE_REVIEWS_API_KEY R2_ACCOUNT_ID R2_ACCESS_KEY_ID "
    "R2_SECRET_ACCESS_KEY R2_BUCKET_NAME R2_PUBLIC_BASE_URL R2_PRIVATE_BUCKET_NAME R2_PRIVATE_ACCESS_KEY_ID "
    "R2_PRIVATE_SECRET_ACCESS_KEY ALERT_WEBHOOK_URL ALERT_WEBHOOK_PROVIDER PUBLIC_API_BASE_URL DATABASE_URL"
).split()
for _name in _PROVIDER_ENV:
    os.environ.pop(_name, None)
_DB = E2E_DIR / "e2e.db"
_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.chdir(E2E_DIR)  # no .env here
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402

_UNSET = [n.lower() for n in _PROVIDER_ENV if n not in ("DATABASE_URL", "PUBLIC_API_BASE_URL")]
_LEAKED = [name for name in _UNSET if getattr(settings, name, None)]
if _LEAKED or not settings.database_url.startswith("sqlite:///") or str(E2E_DIR) not in settings.database_url:
    sys.exit(f"refusing to run: non-isolated settings {_LEAKED or settings.database_url!r}")

from app.creative.frontend_engine.browser_qa import parse_headers_file, run_browser_qa  # noqa: E402
from app.creative.frontend_engine.build import artifact_headers  # noqa: E402
from app.creative.source_adapter.fixtures import (  # noqa: E402
    lumen_physio_business_config,
    nexo_reformas_business_config,
)
from app.creative.source_adapter.preview import serve_artifact  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models.analytics_event import AnalyticsEvent  # noqa: E402
from app.db.models.business import Business  # noqa: E402
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact  # noqa: E402
from app.db.models.lead import Lead  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_access import TenantAccess  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.db.models.website_draft import WebsiteDraft  # noqa: E402
from app.dependencies import engine  # noqa: E402
from app.domain.business_truth import derive_business_truth  # noqa: E402
from app.domain.enums import BusinessStatus, GenerationEngine, UserRole, WebsiteDraftStatus  # noqa: E402
from app.main import app  # noqa: E402
from app.publishing.artifact_store import artifact_sha256, pack_artifact, unpack_artifact  # noqa: E402
from app.publishing.csp_policy import policy_for  # noqa: E402
from app.publishing.drafts import judge_generative_candidate, run_visual_qa_for_draft  # noqa: E402
from app.qa.platform_contract import validate_platform_contract  # noqa: E402
from app.qa.truth_contract import validate_truth_contract  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.storage import LocalStorageProvider  # noqa: E402
from app.storage.private import PrivateArtifactStorage  # noqa: E402

API_PORT = 8765
API = f"http://127.0.0.1:{API_PORT}"
_REFERENCE_PATTERN = re.compile(r"/\s*[A-Z0-9]{8}\b")
_WATCH = """window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
"""
PROFILES = {
    "nexo-reformas": {
        "config": nexo_reformas_business_config,
        "origin": "https://nexo-reformas.example",
        "title": "Nexo Reformas | Reformas de vivienda en Valencia",
        "fonts": ['700 16px "Cabinet Grotesk"', '400 16px "Inter Tight"', '400 16px "IBM Plex Mono"'],
        "consent": ("Aceptar todo", "Rechazar no esenciales"),
        "success": (".nx-sent", "SOLICITUD RECIBIDA"),
        "failure": "NO HEMOS PODIDO ENVIAR LA SOLICITUD",
        "values": {"name": "Prueba H2", "email": "prueba@example.com", "phone": "600 000 000",
                   "message": "Reformar la cocina completa", "detail": "80"},
        "videos": 6,
        "offsets": {"desktop": [0, 900, 1800], "mobile": [0, 844, 1688]},
    },
    "lumen-physio": {
        "config": lumen_physio_business_config,
        "origin": "https://lumen-physio.example",
        "title": "Lumen Physio — Physiotherapy in Lisbon",
        "fonts": ['600 16px "Fraunces"', '400 16px "Inter"'],
        "consent": ("Accept all", "Reject non-essential"),
        "success": (".contact__done", "THANKS"),
        "failure": "SOMETHING WENT WRONG",
        "values": {"name": "Test H2", "email": "test@example.com", "phone": "+351 210 000 000",
                   "message": "Knee pain after running", "detail": "Afternoon"},
        "videos": 0,
        "offsets": {"desktop": [0, 700, 1400], "mobile": [0, 844, 1688]},
    },
}  # fmt: skip
PROFILE = PROFILES[ARGS.fixture]
BUSINESS_ID = uuid.uuid5(uuid.NAMESPACE_URL, f"https://gwa.local/h1/{ARGS.fixture}")  # = h2_source_adapter
ORIGIN = PROFILE["origin"]


def check(results: list, name: str, passed: object, detail: object = "") -> None:
    results.append({"test": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail and not passed else ""))


def diff_images(a: Path, b: Path) -> dict:
    left, right = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if left.size != right.size:
        return {"comparable": False}
    pixels = list(ImageChops.difference(left, right).getdata())
    changed = [i for i, p in enumerate(pixels) if max(p) > 32]
    rows = sorted({i // left.width for i in changed})
    return {
        "comparable": True,
        "pct_pixels_changed": round(100 * len(changed) / len(pixels), 3),
        "changed_rows": [rows[0], rows[-1]] if rows else None,
    }


def seed(password: str) -> tuple[uuid.UUID, str]:
    Base.metadata.create_all(engine)
    config = PROFILE["config"]()
    with Session(engine) as session:
        tenant = Tenant(name="H2 QA tenant")
        session.add(tenant)
        session.flush()
        session.add(
            Business(
                id=BUSINESS_ID,
                tenant_id=tenant.id,
                name=config.business_profile.name,
                slug=config.business_profile.slug,
                vertical=config.business_profile.industry,
                raw_description="Fictional H2 QA business (owner brief only).",
                status=BusinessStatus.DRAFT,
                config=config.model_dump(mode="json"),
            )
        )
        user = User(email="h2-qa-operator@example.com", hashed_password=hash_password(password))
        session.add(user)
        session.flush()
        session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
        session.commit()
        return tenant.id, user.email


def start_api() -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("the local GWA API did not start")


def db_count(model, **where) -> int:
    with Session(engine) as session:
        stmt = select(func.count()).select_from(model)
        for key, value in where.items():
            stmt = stmt.where(getattr(model, key) == value)
        return session.scalar(stmt) or 0


def main() -> None:  # noqa: C901 — a linear QA script
    from playwright.sync_api import sync_playwright

    out = WORK_ROOT / "qa"
    out.mkdir(exist_ok=True)
    report = json.loads((WORK_ROOT / "report.json").read_text(encoding="utf-8"))
    plan = json.loads((WORK_ROOT / "adaptation-plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((WORK_ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    app_dir = WORK_ROOT / "adapted" / manifest["snapshot"]["app_dir"]
    legal = json.loads((app_dir / "src/platform/legal-content.json").read_text(encoding="utf-8"))
    archive = (WORK_ROOT / "artifact.tar.gz").read_bytes()
    artifact = unpack_artifact(archive)
    files = artifact.files
    results: list[dict] = []
    config = PROFILE["config"]()
    truth = derive_business_truth(business_config=config)
    policy = policy_for(plan["csp"]["family"])
    mapping = plan["form_mappings"][0]
    locale = plan["site"]["locale"]

    # --- Identity, plan, contracts, CSP ---------------------------------------------------
    check(results, "artifact_sha256_verifiable", artifact_sha256(artifact) == report["artifact"]["sha256"])
    check(results, "packaging_deterministic", pack_artifact(unpack_artifact(archive)) == archive)
    check(
        results,
        "plan_bound_to_snapshot_and_manifest",
        plan["snapshot_zip_sha256"] == report["source"]["zip_sha256"]
        and plan["manifest_sha256"] == manifest["manifest_sha256"],
    )
    platform = validate_platform_contract(files, business_config=config)
    truth_result = validate_truth_contract(files, business_truth=truth)
    check(results, "platform_contract_passes", platform.passed, [f.rule for f in platform.findings])
    check(results, "truth_contract_passes", truth_result.passed, [f.rule for f in truth_result.findings])
    rederived = artifact_headers(
        {k: v for k, v in files.items() if k != "_headers"}, api_base_url=API, csp_extensions=policy
    )
    check(results, "intake_rederivation_equals_stored_headers", rederived == files["_headers"])
    stored_csp = dict(parse_headers_file(files["_headers"]))["Content-Security-Policy"]
    directives = dict(part.strip().split(" ", 1) for part in stored_csp.split(";"))
    check(
        results,
        "csp_is_the_family_policy_and_nothing_more",
        directives["connect-src"] == f"'self' {API}"
        and "unsafe-eval" not in stored_csp
        and "'unsafe-inline'" not in directives["script-src"]
        and all(o in directives["style-src"] for o in policy.style_origins)
        and all(o in directives["font-src"] for o in policy.font_origins),
        directives,
    )
    check(results, "no_server_bundle_in_artifact", not [p for p in files if p.endswith("server.js")])
    expected_pages = plan["build"]["expected_pages"]
    check(results, "every_planned_page_prerendered", set(expected_pages) <= set(files), expected_pages)

    password = secrets.token_urlsafe(24)
    tenant_id, email = seed(password)
    api = start_api()

    offsets = PROFILE["offsets"]
    if ARGS.offsets and ARGS.offsets.exists():
        spike = json.loads(ARGS.offsets.read_text(encoding="utf-8"))
        offsets = {name: [s["y"] for s in spike[name]["shots"]] for name in ("desktop", "mobile")}

    def events() -> int:
        return db_count(AnalyticsEvent, business_id=BUSINESS_ID)

    visual: dict[str, list] = {}
    brand_srcs = [b["path"] for b in manifest["brand_assets"] if b["kind"] == "rendered-brand-image"]
    allowed_hosts = {o.split("//", 1)[1] for o in (*policy.style_origins, *policy.font_origins)}
    with serve_artifact(artifact) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])

        def context(width=1440, height=900, consent: str | None = "rejected", reduced=False):
            motion = "reduce" if reduced else "no-preference"
            ctx = browser.new_context(viewport={"width": width, "height": height}, reduced_motion=motion)
            script = _WATCH
            if consent == "rejected":
                value = json.dumps(
                    {
                        "necessary": True,
                        "analytics": False,
                        "marketing": False,
                        "preferences": False,
                        "updatedAt": "2026-01-01T00:00:00Z",
                    }
                )
                script += f"try{{localStorage.setItem('gwa-consent', {json.dumps(value)})}}catch(e){{}}"
            ctx.add_init_script(script)
            return ctx

        # --- Homepage: hydration, CSP, fonts, SEO, brand -------------------------------
        ctx = context()
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        response = page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(results, "homepage_loads", response is not None and response.status == 200)
        served = response.headers.get("content-security-policy") if response else None
        check(results, "served_csp_equals_stored_headers", served == stored_csp)
        fonts = page.evaluate(
            "async (specs) => { await document.fonts.ready; return specs.map(s => document.fonts.check(s)); }",
            PROFILE["fonts"],
        )
        check(results, "fonts_loaded_live_tier", all(fonts), dict(zip(PROFILE["fonts"], fonts, strict=True)))
        rendered_marks = page.evaluate(
            "(srcs) => [...document.images].filter(i => srcs.includes(i.getAttribute('src'))).length", brand_srcs
        )
        check(results, "generated_brand_mark_not_rendered", bool(brand_srcs) and rendered_marks == 0, brand_srcs)
        if PROFILE["videos"]:
            height = page.evaluate("document.documentElement.scrollHeight")
            chapters, times = set(), []
            rail = "[...document.querySelectorAll('.nx-journey-rail__item')].findIndex(a => a.dataset.active==='true')"
            for y in range(0, height, 450):
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(120)
                chapters.add(page.evaluate(rail))
                times.append(page.evaluate("[...document.querySelectorAll('video')].map(v => v.currentTime)"))
            page.wait_for_timeout(1500)
            videos = page.evaluate(
                "[...document.querySelectorAll('video')]"
                ".map(v => ({src: v.currentSrc.slice(0,5), ready: v.readyState}))"
            )
            check(
                results,
                "all_videos_play_from_blob",
                len(videos) == PROFILE["videos"] and all(v["src"] == "blob:" and v["ready"] >= 2 for v in videos),
                videos,
            )
            check(results, "scroll_drives_all_chapters", set(range(PROFILE["videos"])) <= chapters, sorted(chapters))
            check(results, "video_time_follows_scroll", any(max(t, default=0) > 1 for t in times))
        violations = page.evaluate("window.__csp")
        check(results, "no_csp_violations", not violations, violations)
        check(results, "no_console_or_hydration_errors", not errors, errors)
        third = {
            re.sub(r"^https?://([^/]+).*$", r"\1", u)
            for u in requests
            if u.startswith("http") and not u.startswith((base, API))
        }
        check(results, "third_party_origins_within_family_policy", third <= allowed_hosts, sorted(third))
        seo = page.evaluate(
            """() => { const m = s => document.querySelector(s)?.getAttribute('content') ?? null;
              const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent);
              return { lang: document.documentElement.lang, title: document.title,
                description: m('meta[name="description"]'), ogImage: m('meta[property="og:image"]'),
                ogUrl: m('meta[property="og:url"]'),
                canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') ?? null, ld }; }"""
        )
        ld = json.loads(seo["ld"][-1]) if seo["ld"] else {}
        check(
            results,
            "seo_metadata",
            seo["lang"] == locale
            and seo["title"] == PROFILE["title"]
            and seo["description"]
            and seo["canonical"] == f"{ORIGIN}/"
            and seo["ogUrl"] == f"{ORIGIN}/"
            and seo["ogImage"] == f"{ORIGIN}/og-image.jpg",
            seo,
        )
        check(
            results,
            "structured_data_is_truth_only",
            ld.get("name") == truth.identity.name
            and [o["itemOffered"]["name"] for o in ld.get("makesOffer", [])] == [s.name for s in truth.services]
            and not {"aggregateRating", "review", "telephone", "address", "foundingDate"} & set(ld),
            ld,
        )
        with Image.open(io.BytesIO(files["og-image.jpg"])) as og:
            check(results, "owned_og_image_1200x630", og.size == (1200, 630), og.size)
        sitemap = files["sitemap.xml"].decode()
        check(
            results,
            "sitemap_lists_every_page",
            f"<loc>{ORIGIN}/</loc>" in sitemap and sitemap.count("<loc>") == len(expected_pages),
        )
        check(results, "robots_txt", f"Sitemap: {ORIGIN}/sitemap.xml" in files["robots.txt"].decode())
        page.screenshot(path=str(out / "home-desktop.png"))
        ctx.close()

        # --- Legal routes ---------------------------------------------------------------------
        for slug, content in legal["pages"].items():
            ctx = context()
            page = ctx.new_page()
            response = page.goto(f"{base}/{slug}", wait_until="networkidle")
            ok = (
                response is not None
                and response.status == 200
                and page.locator("h1").inner_text() == content["title"]
                and page.title() == content["metaTitle"]
                and page.locator('link[rel="canonical"]').get_attribute("href") == f"{ORIGIN}/{slug}"
                and page.locator("article").get_attribute("lang") == locale
            )
            check(results, f"legal_route_{slug}", ok, content["title"])
            page.screenshot(path=str(out / f"legal-{slug}-desktop.png"))
            ctx.close()

        # --- Consent + analytics gating, incl. withdrawal ----------------------------------------
        before = events()
        ctx = context(consent=None)
        page = ctx.new_page()
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        banner = page.locator("#gwa-consent-banner")
        accept_text, reject_text = PROFILE["consent"]
        check(
            results,
            "consent_banner_in_site_language",
            banner.is_visible() and accept_text in banner.inner_text() and reject_text in banner.inner_text(),
        )
        page.screenshot(path=str(out / "consent-banner-desktop.png"))
        check(results, "no_analytics_before_consent", events() == before)
        page.click("#gwa-consent-reject")
        page.wait_for_timeout(1000)
        check(results, "no_analytics_after_reject", events() == before)
        page.locator("footer [data-open-consent-preferences]").first.click()
        page.click("#gwa-consent-accept")
        page.wait_for_timeout(1500)
        after_accept = events()
        check(results, "analytics_recorded_after_accept", after_accept > before, after_accept - before)
        page.locator("footer [data-open-consent-preferences]").first.click()
        page.click("#gwa-consent-reject")  # withdrawal
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(results, "withdrawal_stops_analytics", events() == after_accept, events() - after_accept)
        check(results, "consent_choice_persists", not banner.is_visible())
        ctx.close()

        # --- Lead form -> real API -> database -> Studio (driven by the FormMapping) --------------
        form_selector = 'form[data-gwa-lead-form="lead-1"]'

        def form_page():
            c = context()
            p = c.new_page()
            p.goto(base + "/", wait_until="networkidle")
            p.locator(form_selector).scroll_into_view_if_needed()
            return c, p

        def fill(p) -> tuple[dict, list]:
            """Fill every mapped field by its ROLE; returns what the lead must hold."""
            expected: dict[str, object] = {"consent_given": False}
            details: list[dict] = []
            for field in mapping["fields"]:
                locator = p.locator(f'{form_selector} [name="{field["name"]}"]')
                role = field["role"]
                if field["element"] == "select":
                    options = locator.locator("option")
                    index = 1 if options.count() > 1 else 0
                    value = options.nth(index).get_attribute("value")
                    shown = options.nth(index).inner_text().strip()
                    locator.select_option(value)
                elif locator.get_attribute("type") == "checkbox":
                    locator.check()
                    shown = "true"
                else:
                    shown = PROFILE["values"].get(role, PROFILE["values"]["detail"])
                    locator.fill(shown)
                if role == "consent":
                    expected["consent_given"] = True
                elif role in ("service", "detail"):
                    details.append({"key": field["key"], "label": field["label"], "value": shown})
                    if role == "service":
                        expected["subject"] = shown
                else:
                    expected[role] = shown
            return expected, details

        ctx, page = form_page()
        page.locator(f"{form_selector} [type=submit]").click()
        page.wait_for_timeout(600)
        check(results, "incomplete_submission_stores_nothing", db_count(Lead) == 0)
        page.locator(form_selector).screenshot(path=str(out / "form-empty-submit.png"))
        ctx.close()

        # The FIRST response never reaches the browser: the real API stores the
        # lead, the platform transport retries with the same submission id.
        ctx, page = form_page()
        attempts: list[str] = []

        def cut_first_response(route):
            attempts.append(route.request.post_data or "")
            if len(attempts) == 1:
                route.fetch()
                route.abort("connectionreset")
            else:
                route.continue_()

        page.route(f"{API}/public/businesses/*/leads", cut_first_response)
        page.wait_for_timeout(2500)  # the real spam-timing minimum is 2 s
        expected, expected_details = fill(page)
        page.locator(f"{form_selector} [type=submit]").click()
        success_selector, success_text = PROFILE["success"]
        page.wait_for_selector(success_selector, timeout=15000)
        sent_text = page.locator(success_selector).inner_text()
        page.locator(success_selector).screenshot(path=str(out / "form-sent.png"))
        ids = {json.loads(a).get("submission_id") for a in attempts}
        check(
            results,
            "retry_reused_the_submission_id",
            len(attempts) == 2 and len(ids) == 1 and None not in ids,
            {"attempts": len(attempts), "ids": len(ids)},
        )
        with Session(engine) as session:
            leads = list(session.scalars(select(Lead).where(Lead.business_id == BUSINESS_ID)).all())
        check(results, "retried_submission_stored_exactly_once", len(leads) == 1, len(leads))
        lead = leads[0] if leads else None
        stored = None
        if lead is not None:
            stored = {
                "name": lead.name,
                "email": lead.email,
                "phone": lead.phone,
                "message": lead.message,
                "subject": lead.subject,
                "consent_given": lead.consent_given,
            }
        want = {k: expected.get(k) for k in ("name", "email", "phone", "message", "subject", "consent_given")}
        check(
            results,
            "lead_persisted_without_data_loss",
            lead is not None and stored == want and lead.details == expected_details and lead.tenant_id == tenant_id,
            {
                "stored": stored,
                "expected": want,
                "details": None if lead is None else lead.details,
                "expected_details": expected_details,
            },
        )
        check(
            results,
            "success_state_without_fabricated_reference",
            success_text in sent_text.upper() and not _REFERENCE_PATTERN.search(sent_text),
            sent_text,
        )
        ctx.close()

        with httpx.Client(base_url=API) as studio:
            login = studio.post("/auth/login", json={"email": email, "password": password})
            listed = studio.get(f"/businesses/{BUSINESS_ID}/leads", headers={"X-Tenant-Id": str(tenant_id)})
        anonymous = httpx.get(f"{API}/businesses/{BUSINESS_ID}/leads", headers={"X-Tenant-Id": str(tenant_id)})
        visible = listed.json()[0] if listed.status_code == 200 and listed.json() else {}
        check(
            results,
            "studio_shows_the_lead_details",
            login.status_code == 200 and visible.get("details") == expected_details,
            {"login": login.status_code, "list": listed.status_code},
        )
        check(results, "studio_leads_require_authentication", anonymous.status_code == 401, anonymous.status_code)
        bodies = (
            {"name": "Sin contacto", "company_website": ""},
            {"name": "x", "phone": "600000000", "details": [{"key": "Bad Key", "label": "x", "value": "y"}]},
            {"name": "x", "phone": "600000000", "unexpected": "field"},
        )
        statuses = [httpx.post(f"{API}/public/businesses/{BUSINESS_ID}/leads", json=b).status_code for b in bodies]
        check(results, "invalid_submissions_rejected_by_real_api", statuses == [422, 422, 422], statuses)

        ctx, page = form_page()
        page.route(f"{API}/public/businesses/*/leads", lambda r: r.fulfill(status=503, body="{}"))
        page.wait_for_timeout(2500)
        fill(page)
        page.locator(f"{form_selector} [type=submit]").click()
        page.wait_for_timeout(1500)
        failed = PROFILE["failure"] in page.locator(form_selector).inner_text().upper()
        check(results, "failure_state_shown", failed and page.locator(success_selector).count() == 0)
        page.locator(form_selector).screenshot(path=str(out / "form-failure.png"))
        ctx.close()

        stored_before = db_count(Lead)
        ctx, page = form_page()
        page.wait_for_timeout(2500)
        fill(page)
        page.evaluate(f"document.querySelector('{form_selector} [name=hp_field]').value = 'https://spam.example'")
        page.locator(f"{form_selector} [type=submit]").click()
        page.wait_for_selector(success_selector, timeout=15000)
        check(results, "honeypot_submission_not_stored", db_count(Lead) == stored_before)
        ctx.close()

        # --- Visual: fixed offsets, compared with the accepted baseline -------------------------
        for name, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
            ctx = context(width, height)
            page = ctx.new_page()
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_timeout(1500)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            rows = []
            for i, y in enumerate(offsets[name]):
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(900)
                shot = out / f"adapted-{name}-{i:02d}.png"
                page.screenshot(path=str(shot))
                row: dict[str, object] = {"i": i, "y": y}
                baseline = ARGS.baseline / f"adapted-{name}-{i:02d}.png" if ARGS.baseline else None
                if baseline is not None and baseline.exists():
                    row.update(diff_images(baseline, shot))
                rows.append(row)
            visual[name] = rows
            check(results, f"no_horizontal_overflow_{name}", overflow <= 0, overflow)
            ctx.close()
        ctx = context(reduced=True)
        page = ctx.new_page()
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out / "reduced-motion-00.png"))
        check(results, "reduced_motion_renders_content", page.locator("h1, h2").count() > 0)
        ctx.close()
        browser.close()

    existing = run_browser_qa(files)
    failures = [f"{f.viewport}:{f.check} {f.detail}"[:200] for f in existing.failures]
    check(results, "gwa_browser_qa_passes_every_check", not failures, failures)

    # --- Real approval-flow evidence: intake gate -> Visual QA (sandboxed) -> Studio ----------------
    private = PrivateArtifactStorage(LocalStorageProvider(root_dir=E2E_DIR / "private"))
    public = LocalStorageProvider(root_dir=E2E_DIR / "public")
    with Session(engine) as session:
        draft = WebsiteDraft(
            tenant_id=tenant_id,
            business_id=BUSINESS_ID,
            engine=GenerationEngine.GENERATIVE,
            site_config=None,
            status=WebsiteDraftStatus.BUILDING,
        )
        session.add(draft)
        session.flush()
        session.add(
            GenerativeWebsiteArtifact(
                tenant_id=tenant_id,
                business_id=BUSINESS_ID,
                website_draft_id=draft.id,
                framework="tanstack-start",
                workspace_key="h2/none",
                build_command="bun run build",
                output_dir="dist/client",
                dependencies=[],
                platform_contract_version=platform.version,
                qa_state={},
                generator_provider="higgsfield-export",
                generated_at=datetime.now(UTC),
            )
        )
        session.flush()
        gate = judge_generative_candidate(
            draft=draft,
            files=dict(files),
            business_config=config,
            business_truth=truth,
            artifact_storage=private,
            api_base_url=API,
            csp_extensions=policy,
        )
        check(
            results,
            "intake_gate_ready_with_identity_preserved",
            gate is None
            and draft.status is WebsiteDraftStatus.READY
            and draft.artifact_sha256 == report["artifact"]["sha256"],
            draft.artifact_sha256,
        )
        row = run_visual_qa_for_draft(
            session=session,
            tenant_id=tenant_id,
            business_id=BUSINESS_ID,
            draft_id=draft.id,
            storage=public,
            artifact_storage=private,
        )
        evidence = row.visual_qa_state
        check(
            results,
            "visual_qa_evidence_bound_to_artifact",
            evidence.get("artifact_sha256") == draft.artifact_sha256
            and evidence.get("headers_sha256") == hashlib.sha256(files["_headers"]).hexdigest(),
            {k: evidence.get(k) for k in ("artifact_sha256", "source", "passed")},
        )
        sandbox_failures = [
            f"{f['viewport']}:{f['check']} {f['detail']}"[:160] for f in evidence["findings"] if not f["passed"]
        ]
        check(results, "sandboxed_visual_qa_deterministic_tier", not sandbox_failures, sandbox_failures)
        draft_id = draft.id
        session.commit()
    with httpx.Client(base_url=API) as studio:
        studio.post("/auth/login", json={"email": email, "password": password})
        url = f"/businesses/{BUSINESS_ID}/website-drafts/{draft_id}/generative-artifact"
        read = studio.get(url, headers={"X-Tenant-Id": str(tenant_id)}).json()
        check(results, "studio_sees_current_qa_evidence", read.get("visual_qa_current") is True, read)
        with Session(engine) as session:
            evidence_row = session.scalars(
                select(GenerativeWebsiteArtifact).where(GenerativeWebsiteArtifact.website_draft_id == draft_id)
            ).one()
            # artifact_sha256 is write-once on a draft; stale evidence is QA
            # produced for a different artifact identity.
            evidence_row.visual_qa_state = {**evidence_row.visual_qa_state, "artifact_sha256": "0" * 64}
            session.commit()
        read = studio.get(url, headers={"X-Tenant-Id": str(tenant_id)}).json()
        check(results, "stale_evidence_never_reused", read.get("visual_qa_current") is False)

    api.should_exit = True
    summary = {
        "fixture": ARGS.fixture,
        "artifact_sha256": report["artifact"]["sha256"],
        "passed": [r["test"] for r in results if r["passed"]],
        "failed": [r for r in results if not r["passed"]],
        "visual_vs_baseline": visual,
        "results": results,
    }
    (out / "qa-report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), "utf-8")
    print(json.dumps({"failed": summary["failed"]}, indent=1, ensure_ascii=False, default=str))
    print(f"{len(summary['passed'])} passed, {len(summary['failed'])} failed")


if __name__ == "__main__":
    main()
