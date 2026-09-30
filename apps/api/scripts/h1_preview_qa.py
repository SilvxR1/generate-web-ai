"""H1 local preview QA for an adapted artifact (scripts/h1_higgsfield_adapter.py).

    uv run python scripts/h1_preview_qa.py --work-root /tmp/gwa-h1/run3 \
        --spike-visual /tmp/gwa-higgsfield-portability/visual

- Serves artifact.tar.gz with its OWN `_headers` (real CSP) on 127.0.0.1
  (app.creative.source_adapter.preview.serve_artifact).
- Runs a LOCAL GWA-compatible Lead/Events API on 127.0.0.1:8765 built from
  the real pieces: PublicLeadCreateRequest/Response and
  AnalyticsEventCreateRequest/Response validation, app.leads.spam.is_spam,
  PublicEndpointCORSMiddleware. Storage is an in-memory list (no database,
  nothing leaves the machine).
- Drives Chromium (Playwright) through the functional checks, captures
  screenshots at the spike's exact scroll offsets and diffs them against
  the spike's independent render of the ORIGINAL export.
Writes <work-root>/qa/qa-report.json and screenshots.
"""

import argparse
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `uv run python scripts/...` works without a separate PYTHONPATH

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from app.creative.frontend_engine.browser_qa import parse_headers_file, run_browser_qa  # noqa: E402
from app.creative.frontend_engine.build import artifact_headers  # noqa: E402
from app.creative.source_adapter.mappings.nexo_reformas import h1_fixture_business_config  # noqa: E402
from app.creative.source_adapter.preview import serve_artifact  # noqa: E402
from app.domain.business_truth import derive_business_truth  # noqa: E402
from app.leads.spam import is_spam  # noqa: E402
from app.publishing.artifact_store import artifact_sha256, pack_artifact, unpack_artifact  # noqa: E402
from app.publishing.csp_policy import policy_for  # noqa: E402
from app.qa.platform_contract import validate_platform_contract  # noqa: E402
from app.qa.truth_contract import validate_truth_contract  # noqa: E402
from app.schemas.analytics import AnalyticsEventCreateRequest, AnalyticsEventCreateResponse  # noqa: E402
from app.schemas.public import PublicLeadCreateRequest, PublicLeadCreateResponse  # noqa: E402
from app.security.public_cors import PublicEndpointCORSMiddleware  # noqa: E402

API_PORT = 8765
_REFERENCE_PATTERN = re.compile(r"/\s*[A-Z0-9]{8}\b")
_WATCH = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
"""


@dataclass
class ApiState:
    leads: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    spam_dropped: int = 0
    fail: bool = False


def make_api(state: ApiState) -> FastAPI:
    api = FastAPI()

    @api.post("/public/businesses/{business_id}/leads", status_code=201, response_model=PublicLeadCreateResponse)
    def create_lead(business_id: str, payload: PublicLeadCreateRequest):
        if state.fail:
            return JSONResponse({"detail": "temporarily unavailable"}, status_code=503)
        if is_spam(honeypot_value=payload.company_website, rendered_at=payload.rendered_at, now=datetime.now(UTC)):
            state.spam_dropped += 1
            return PublicLeadCreateResponse()
        state.leads.append({"business_id": business_id, **payload.model_dump(mode="json")})
        return PublicLeadCreateResponse()

    @api.post("/public/businesses/{business_id}/events", status_code=201, response_model=AnalyticsEventCreateResponse)
    def create_event(business_id: str, payload: AnalyticsEventCreateRequest):
        state.events.append({"business_id": business_id, **payload.model_dump(mode="json")})
        return AnalyticsEventCreateResponse()

    api.add_middleware(PublicEndpointCORSMiddleware)
    return api


def start_api(state: ApiState) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(make_api(state), host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("local API did not start")


class Recorder:
    def __init__(self, page, base: str) -> None:
        self.requests: list[tuple[str, str]] = []
        self.bad: list[str] = []
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        page.on("request", lambda r: self.requests.append((r.method, r.url)))
        page.on("response", lambda r: self.bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)
        page.on("requestfailed", lambda r: self.bad.append(f"FAILED {r.url} {r.failure}"))
        page.on("console", lambda m: self.console_errors.append(m.text[:300]) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:300]))


def check(results: list, name: str, passed: object, detail: object = "") -> None:
    results.append({"test": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail and not passed else ""))


def diff_images(a: Path, b: Path) -> dict:
    left, right = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if left.size != right.size:
        return {"comparable": False, "sizes": [left.size, right.size]}
    pixels = list(ImageChops.difference(left, right).getdata())
    changed = sum(1 for p in pixels if max(p) > 32)
    return {
        "comparable": True,
        "mean_abs_diff": round(sum(sum(p) for p in pixels) / (len(pixels) * 3), 2),
        "pct_pixels_changed": round(100 * changed / len(pixels), 2),
    }


def main() -> None:  # noqa: C901 — a linear QA script
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--spike-visual", type=Path)
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    out = args.work_root / "qa"
    out.mkdir(exist_ok=True)
    report = json.loads((args.work_root / "h1-report.json").read_text(encoding="utf-8"))
    archive = (args.work_root / "artifact.tar.gz").read_bytes()
    artifact = unpack_artifact(archive)
    results: list[dict] = []

    # --- Packaging / identity / contracts (re-verified on the stored archive)
    check(results, "artifact_sha256_verifiable", artifact_sha256(artifact) == report["artifact"]["sha256"])
    check(results, "packaging_deterministic", pack_artifact(unpack_artifact(archive)) == archive)
    config = h1_fixture_business_config()
    platform = validate_platform_contract(artifact.files, business_config=config)
    truth = validate_truth_contract(artifact.files, business_truth=derive_business_truth(business_config=config))
    check(results, "platform_contract_passes", platform.passed, [f.rule for f in platform.findings])
    check(results, "truth_contract_passes", truth.passed, [f.rule for f in truth.findings])
    # H1.1: trusted intake re-derives `_headers` from the job's family; it must
    # reproduce the stored bytes exactly (else the candidate would be rejected).
    rederived = artifact_headers(
        {k: v for k, v in artifact.files.items() if k != "_headers"},
        api_base_url=f"http://127.0.0.1:{API_PORT}",
        csp_extensions=policy_for(report["source_family"]),
    )
    check(results, "intake_rederivation_equals_stored_headers", rederived == artifact.files["_headers"])
    stored_csp = dict(parse_headers_file(artifact.files["_headers"]))["Content-Security-Policy"]
    server_files = [p for p in artifact.files if p.endswith("server.js") or p.startswith("server/")]
    check(results, "no_server_bundle_in_artifact", not server_files, server_files)

    state = ApiState()
    api = start_api(state)
    spike_shots: dict[str, list[int]] = {}
    if args.spike_visual and (args.spike_visual / "report.json").exists():
        spike = json.loads((args.spike_visual / "report.json").read_text(encoding="utf-8"))
        spike_shots = {name: [s["y"] for s in spike[name]["shots"]] for name in ("desktop", "mobile")}

    with serve_artifact(artifact) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])

        def context(width=1440, height=900, consent: str | None = "rejected", reduced=False):
            ctx = browser.new_context(
                viewport={"width": width, "height": height}, reduced_motion="reduce" if reduced else "no-preference"
            )
            script = _WATCH
            if consent:
                granted = "true" if consent == "accepted" else "false"
                record = (
                    f'{{"necessary":true,"analytics":{granted},"marketing":{granted},'
                    f'"preferences":{granted},"updatedAt":"2026-01-01T00:00:00Z"}}'
                )
                script += f"try{{localStorage.setItem('gwa-consent', {json.dumps(record)})}}catch(e){{}}"
            ctx.add_init_script(script)
            return ctx

        # --- Homepage, assets, hydration, CSP -------------------------------
        ctx = context()
        page = ctx.new_page()
        rec = Recorder(page, base)
        response = page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check(results, "homepage_loads", response is not None and response.status == 200)
        served_csp = response.headers.get("content-security-policy") if response is not None else None
        check(results, "served_csp_equals_stored_headers", served_csp == stored_csp, served_csp)
        check(
            results, "document_title", page.title() == "Nexo Reformas | Reformas de vivienda en Valencia", page.title()
        )
        info = page.evaluate(
            """async () => { await document.fonts.ready; return {
              cabinet: document.fonts.check('700 16px "Cabinet Grotesk"'),
              inter: document.fonts.check('400 16px "Inter Tight"'),
              plex: document.fonts.check('400 16px "IBM Plex Mono"'),
              gwa: typeof window.gwaConsent === 'object' && typeof window.gwaAnalytics === 'object',
              h: document.documentElement.scrollHeight }; }"""
        )
        check(results, "fonts_loaded", info["cabinet"] and info["inter"] and info["plex"], info)
        check(results, "platform_sdk_globals", info["gwa"])
        times, chapters = [], set()
        for y in range(0, info["h"], 450):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(120)
            chapters.add(
                page.evaluate(
                    "[...document.querySelectorAll('.nx-journey-rail__item')]"
                    ".findIndex(a => a.dataset.active === 'true')"
                )
            )
            times.append(page.evaluate("[...document.querySelectorAll('video')].map(v => v.currentTime)"))
        page.wait_for_timeout(1500)
        videos = page.evaluate(
            "[...document.querySelectorAll('video')].map(v => ({src: v.currentSrc.slice(0,5), ready: v.readyState}))"
        )
        check(
            results,
            "journey_videos_play_from_blob",
            len(videos) == 6 and all(v["src"] == "blob:" and v["ready"] >= 2 for v in videos),
            videos,
        )
        check(results, "scroll_drives_all_six_chapters", {0, 1, 2, 3, 4, 5} <= chapters, sorted(chapters))
        check(results, "video_time_follows_scroll", any(max(t, default=0) > 1 for t in times))
        local_bad = [b for b in rec.bad if base in b]
        check(results, "all_local_assets_resolve", not local_bad, local_bad[:10])
        remote = sorted(
            {
                re.sub(r"^https?://([^/]+).*$", r"\1", u)
                for _, u in rec.requests
                if not u.startswith((base, f"blob:{base}", "data:"))  # same-origin object URLs are local
            }
            - {""}
        )
        check(
            results,
            "remote_origins_only_fontshare_and_gwa_api",
            set(remote) <= {"api.fontshare.com", "cdn.fontshare.com", f"127.0.0.1:{API_PORT}"},
            remote,
        )
        check(
            results,
            "no_higgsfield_or_server_fn_requests",
            not [u for _, u in rec.requests if "higgsfield" in u or "_serverFn" in u],
        )
        violations = page.evaluate("window.__csp")
        check(results, "no_csp_violations", not violations, violations)
        check(
            results,
            "no_console_or_hydration_errors",
            not rec.console_errors and not rec.page_errors,
            rec.console_errors + rec.page_errors,
        )
        ctx.close()

        # --- SEO / robots / sitemap -----------------------------------------
        ctx = context()
        page = ctx.new_page()
        page.goto(base + "/", wait_until="domcontentloaded")
        seo = page.evaluate(
            """() => { const m = s => document.querySelector(s)?.getAttribute('content') ?? null; return {
              lang: document.documentElement.lang, description: m('meta[name="description"]'),
              viewport: m('meta[name="viewport"]'), robots: m('meta[name="robots"]'),
              ogTitle: m('meta[property="og:title"]'), ogLocale: m('meta[property="og:locale"]'),
              ogSite: m('meta[property="og:site_name"]'), ogImage: m('meta[property="og:image"]'),
              twitter: m('meta[name="twitter:card"]') }; }"""
        )
        check(
            results,
            "seo_metadata",
            seo["lang"] == "es"
            and seo["description"]
            and seo["viewport"]
            and seo["ogTitle"]
            and seo["ogLocale"] == "es_ES"
            and seo["ogSite"] == "Nexo Reformas"
            and seo["ogImage"] is None
            and seo["robots"] == "index, follow",
            seo,
        )
        robots = page.request.get(base + "/robots.txt")
        sitemap = page.request.get(base + "/sitemap.xml")
        check(
            results,
            "robots_txt",
            robots.status == 200 and "Sitemap: https://nexo-reformas.example/sitemap.xml" in robots.text(),
            robots.headers.get("content-type"),
        )
        check(
            results,
            "sitemap_xml",
            sitemap.status == 200 and sitemap.text().count("<loc>") == 4,
            sitemap.headers.get("content-type"),
        )
        ctx.close()

        # --- Legal routes ----------------------------------------------------
        for slug, title in (("privacy", "Privacy Policy"), ("terms", "Terms of Service"), ("cookies", "Cookie Policy")):
            ctx = context()
            page = ctx.new_page()
            rec = Recorder(page, base)
            response = page.goto(f"{base}/{slug}", wait_until="networkidle")
            ok = (
                response is not None
                and response.status == 200
                and page.locator("h1").inner_text() == title
                and page.title() == f"{title} — Nexo Reformas"
                and page.locator('a[href="/"]').count() >= 2
                and page.locator("#gwa-consent-banner").count() == 1
            )
            check(results, f"legal_route_{slug}", ok and not rec.page_errors and not page.evaluate("window.__csp"))
            if slug == "privacy":
                page.screenshot(path=str(out / "legal-privacy-desktop.png"))
            ctx.close()
        ctx = context(390, 844)
        page = ctx.new_page()
        page.goto(f"{base}/privacy", wait_until="networkidle")
        page.screenshot(path=str(out / "legal-privacy-mobile.png"))
        ctx.close()
        ctx = context()
        page = ctx.new_page()
        page.goto(base + "/", wait_until="networkidle")
        page.locator('footer a[href="/terms"]').click()
        page.wait_for_load_state("networkidle")
        check(results, "footer_legal_link_navigates", page.url.rstrip("/").endswith("/terms"), page.url)
        ctx.close()

        # --- Consent + consent-aware analytics -------------------------------
        state.events.clear()
        ctx = context(consent=None)
        page = ctx.new_page()
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1500)
        banner = page.locator("#gwa-consent-banner")
        check(results, "consent_banner_shown_without_decision", banner.is_visible())
        page.screenshot(path=str(out / "consent-banner-desktop.png"))
        check(results, "no_analytics_before_consent", not state.events, state.events)
        page.click("#gwa-consent-reject")
        page.wait_for_timeout(1000)
        stored = json.loads(page.evaluate("localStorage.getItem('gwa-consent')") or "{}")
        check(
            results,
            "reject_hides_banner_and_stores_choice",
            not banner.is_visible() and stored.get("analytics") is False,
        )
        check(results, "no_analytics_after_reject", not state.events, state.events)
        page.locator("footer [data-open-consent-preferences]").click()
        page.wait_for_timeout(300)
        check(results, "cookie_preferences_reopen_banner", banner.is_visible())
        page.click("#gwa-consent-accept")
        page.wait_for_timeout(1500)
        kinds = [e["event_type"] for e in state.events]
        check(results, "analytics_flushed_after_accept", "page_view" in kinds, kinds)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)
        check(results, "consent_persists_across_reload", not banner.is_visible())
        ctx.close()
        ctx = context(390, 844, consent=None)
        page = ctx.new_page()
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out / "consent-banner-mobile.png"))
        ctx.close()

        # --- Lead form -------------------------------------------------------
        def form_page():
            c = context()
            p = c.new_page()
            p.goto(base + "/", wait_until="networkidle")
            p.locator("form.nx-form").scroll_into_view_if_needed()
            return c, p

        state.leads.clear()
        ctx, page = form_page()
        page.click("button.nx-cta-submit")
        page.wait_for_timeout(500)
        errors = page.locator(".nx-field__error").all_inner_texts()
        check(
            results,
            "client_validation_blocks_empty_submit",
            [e.lower() for e in errors] == ["escribe tu nombre", "teléfono incompleto"] and not state.leads,
            errors,
        )
        page.locator("form.nx-form").screenshot(path=str(out / "form-errors.png"))
        page.fill("#name", "Prueba H1")
        page.fill("#phone", "600000000")
        page.fill("#email", "no-es-un-correo")
        page.click("button.nx-cta-submit")
        page.wait_for_timeout(500)
        errors = page.locator(".nx-field__error").all_inner_texts()
        check(
            results,
            "client_validation_blocks_invalid_email",
            "revisa el correo" in [e.lower() for e in errors] and not state.leads,
            errors,
        )
        ctx.close()

        ctx, page = form_page()
        page.wait_for_timeout(2500)  # the real spam-timing minimum is 2 s
        page.fill("#name", "Prueba H1")
        page.fill("#phone", "600 000 000")
        page.fill("#email", "prueba@example.com")
        page.fill("#area", "80")
        page.select_option("#scope", "cocina")
        page.fill("#notes", "Reformar la cocina completa")
        page.click("button.nx-cta-submit")
        page.wait_for_selector(".nx-sent", timeout=15000)
        sent_text = page.locator(".nx-sent").inner_text()
        page.locator(".nx-sent").screenshot(path=str(out / "form-sent.png"))
        lead = state.leads[-1] if state.leads else {}
        check(results, "valid_submission_reaches_gwa_api", bool(lead), lead)
        check(
            results,
            "lead_payload_mapping",
            lead.get("name") == "Prueba H1"
            and lead.get("phone") == "600 000 000"
            and lead.get("email") == "prueba@example.com"
            and lead.get("subject") == "Cocina"
            and lead.get("message") == "Reformar la cocina completa\n\nSuperficie aproximada: 80"
            and lead.get("consent") is False
            and str(lead.get("source_url", "")).startswith(base),
            lead,
        )
        check(
            results,
            "success_state_without_fabricated_reference",
            "SOLICITUD RECIBIDA" in sent_text.upper()
            and "Gracias. Ya tenemos tus datos." in sent_text
            and not _REFERENCE_PATTERN.search(sent_text),
            sent_text,
        )
        ctx.close()

        ctx, page = form_page()
        statuses = page.evaluate(
            f"""async () => {{
              const url = 'http://127.0.0.1:{API_PORT}/public/businesses/' +
                JSON.parse(document.getElementById('platform-config').textContent).businessId + '/leads';
              const post = body => fetch(url, {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(body)}}).then(r => r.status);
              return [await post({{name: 'Sin contacto', consent: false, company_website: ''}}),
                      await post({{name: 'x', phone: '600000000', email: 'no-es-un-correo', company_website: ''}}),
                      await post({{name: 'x', phone: '600000000', unexpected: 'field', company_website: ''}})];
            }}"""
        )
        check(results, "invalid_submission_rejected_by_api", statuses == [422, 422, 422], statuses)
        ctx.close()

        state.fail = True
        ctx, page = form_page()
        page.wait_for_timeout(2500)
        page.fill("#name", "Prueba H1")
        page.fill("#phone", "600000000")
        page.click("button.nx-cta-submit")
        page.wait_for_timeout(1500)
        failure = page.locator("form.nx-form").inner_text()
        page.locator("form.nx-form").screenshot(path=str(out / "form-failure.png"))
        check(
            results,
            "failure_state_shown",
            # The site's CSS uppercases the message; innerText reflects that.
            "NO HEMOS PODIDO ENVIAR LA SOLICITUD" in failure.upper() and page.locator(".nx-sent").count() == 0,
        )
        state.fail = False
        ctx.close()

        stored_before = len(state.leads)
        ctx, page = form_page()
        page.wait_for_timeout(2500)
        page.fill("#name", "Bot")
        page.fill("#phone", "600000000")
        page.evaluate("document.getElementById('hp_field').value = 'https://spam.example'")
        page.click("button.nx-cta-submit")
        page.wait_for_selector(".nx-sent", timeout=15000)
        check(results, "honeypot_submission_not_stored", len(state.leads) == stored_before and state.spam_dropped >= 1)
        ctx.close()

        # --- Visual: same absolute offsets as the spike's ORIGINAL render ----
        visual: dict[str, list] = {}
        for name, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
            ctx = context(width, height)
            page = ctx.new_page()
            page.goto(base + "/", wait_until="networkidle")
            page.wait_for_timeout(1500)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            rows = []
            for i, y in enumerate(spike_shots.get(name, [])):
                page.evaluate(f"window.scrollTo(0, {y})")
                page.wait_for_timeout(900)
                shot = out / f"adapted-{name}-{i:02d}.png"
                page.screenshot(path=str(shot))
                row: dict[str, object] = {"i": i, "y": y}
                if args.spike_visual:
                    row.update(diff_images(args.spike_visual / f"{name}-{i:02d}.png", shot))
                rows.append(row)
            visual[name] = rows
            check(results, f"horizontal_overflow_{name}_px", overflow <= 0, overflow)
            ctx.close()
        ctx = context(reduced=True)
        page = ctx.new_page()
        rec = Recorder(page, base)
        page.goto(base + "/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out / "reduced-motion-00.png"))
        reduced = page.evaluate("({headings: document.querySelectorAll('h1,h2').length})")
        check(results, "reduced_motion_renders_content", reduced["headings"] > 0 and not rec.page_errors, reduced)
        ctx.close()
        browser.close()

    # --- GWA's existing browser QA, unchanged (it does not apply _headers) ---
    existing = run_browser_qa(artifact.files)
    for viewport in ("desktop", "tablet", "mobile", "desktop-reduced-motion"):
        gwa = {f.check: f for f in existing.findings if f.viewport == viewport}
        for name in ("artifact_csp_applied", "no_csp_violations", "no_failed_resources", "no_uncaught_page_errors"):
            finding = gwa.get(name)
            check(
                results,
                f"gwa_browser_qa_{viewport}_{name}",
                finding is not None and finding.passed,
                finding.detail if finding else "missing",
            )
    api.should_exit = True

    summary = {
        "passed": [r["test"] for r in results if r["passed"]],
        "failed": [r for r in results if not r["passed"]],
        "leads_received": state.leads,
        "spam_dropped": state.spam_dropped,
        "existing_browser_qa_failures": [f"{f.viewport}:{f.check} {f.detail}"[:200] for f in existing.failures],
        "visual_vs_spike": visual,
        "results": results,
    }
    (out / "qa-report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("failed", "existing_browser_qa_failures")}, indent=1, ensure_ascii=False))
    print(f"{len(summary['passed'])} passed, {len(summary['failed'])} failed")


if __name__ == "__main__":
    main()
