"""R5 full-product E2E: a supervised website export through the REAL GWA
product workflow, locally, with no provider, no deployment and no paid call.

    uv run python scripts/r5_product_e2e.py --fixture nexo-reformas \
        --zip /path/nexo-reformas-web.zip --work-root /tmp/gwa-r5/nexo
    uv run python scripts/r5_product_e2e.py --fixture lumen-physio --work-root /tmp/gwa-r5/lumen

What is real: the FastAPI app (uvicorn) with real login/session/CSRF, the
operator endpoints Studio calls, a throwaway SQLite database, private
storage (a local directory), the generation-worker protocol and a SEPARATE
worker process (`python -m app.worker --once`, its own minimal environment
with no platform secret, cwd without .env) that downloads the snapshot with
its job token, applies the stored plan, installs (`--ignore-scripts`),
builds, assembles, QA's and submits; trusted intake; preview/approve/
publish/rollback through the existing draft/version routes; Chromium on
the preview; the lead form against the real public Lead API.

What is substituted: Cloudflare. The preview and production publishers are
local servers that serve the EXACT artifact they are handed (with its own
`_headers`) — the same boundary the existing tests use.

Isolation: like scripts/h2_e2e_qa.py, the process moves into a scratch dir
(no .env), uses a fresh SQLite file and clears every provider credential
before importing `app`, and refuses to run otherwise.
"""

import argparse
import os
import sys
from pathlib import Path

_PARSER = argparse.ArgumentParser()
_PARSER.add_argument("--fixture", choices=("nexo-reformas", "lumen-physio"), required=True)
_PARSER.add_argument("--zip", type=Path)
_PARSER.add_argument("--work-root", type=Path, required=True)
_PARSER.add_argument("--isolation", choices=("supervised-process", "bubblewrap"), default="supervised-process")
_PARSER.add_argument("--measure", action="store_true", help="wrap the worker in /usr/bin/time -v (peak RSS)")
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
os.environ["PUBLIC_API_BASE_URL"] = "http://127.0.0.1:8765"
os.chdir(E2E_DIR)  # no .env here
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import secrets  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
import zipfile  # noqa: E402
from contextlib import ExitStack  # noqa: E402

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402

_UNSET = [n.lower() for n in _PROVIDER_ENV if n not in ("DATABASE_URL", "PUBLIC_API_BASE_URL")]
_LEAKED = [name for name in _UNSET if getattr(settings, name, None)]
if _LEAKED or str(E2E_DIR) not in settings.database_url:
    sys.exit(f"refusing to run: non-isolated settings {_LEAKED or settings.database_url!r}")

from app.creative.source_adapter.fixtures import (  # noqa: E402
    lumen_physio_business_config,
    nexo_reformas_business_config,
    zip_directory,
)
from app.creative.source_adapter.preview import serve_artifact  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models.business import Business  # noqa: E402
from app.db.models.lead import Lead  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_access import TenantAccess  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.dependencies import (  # noqa: E402
    engine,
    get_optional_preview_publisher,
    get_preview_publisher,
    get_private_artifact_storage,
    get_storage_provider,
    get_website_publisher,
)
from app.domain.enums import BusinessStatus, UserRole  # noqa: E402
from app.main import app  # noqa: E402
from app.publishing.artifact_store import artifact_sha256  # noqa: E402
from app.publishing.publisher import (  # noqa: E402
    PreviewDeployment,
    PreviewPublisher,
    PublishedSite,
    WebsiteArtifact,
    WebsitePublisher,
)
from app.security.passwords import hash_password  # noqa: E402
from app.storage import LocalStorageProvider  # noqa: E402
from app.storage.private import PrivateArtifactStorage  # noqa: E402
from app.worker.auth import hash_worker_token  # noqa: E402

API_PORT = 8765
API = f"http://127.0.0.1:{API_PORT}"
WORKER_TOKEN = secrets.token_hex(32)  # this run only; never a real credential
LUMEN_FIXTURE = API_ROOT / "tests" / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
PROFILES = {
    "nexo-reformas": {
        "config": nexo_reformas_business_config,
        "videos": 6,
        "consent": "Aceptar todo",
        "success": ".nx-sent",
        "values": {"name": "Prueba R5", "email": "prueba@example.com", "phone": "600 000 000",
                   "message": "Reformar la cocina completa", "detail": "80"},
        "edit": (
            "nexo-reformas-web/app/src/routes/index.tsx",
            "Cuéntanos qué quieres cambiar.",
            "Cuéntanos qué quieres reformar.",
        ),
    },
    "lumen-physio": {
        "config": lumen_physio_business_config,
        "videos": 0,
        "consent": "Accept all",
        "success": ".contact__done",
        "values": {"name": "Test R5", "email": "test@example.com", "phone": "+351 210 000 000",
                   "message": "Knee pain after running", "detail": "Afternoon"},
        "edit": ("lumen-physio/src/content/site.ts", "The studio", "Our studio"),
    },
}  # fmt: skip
PROFILE = PROFILES[ARGS.fixture]
RESULTS: list[dict] = []


def check(name: str, passed: object, detail: object = "") -> None:
    RESULTS.append({"test": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail and not passed else ""), flush=True)


class LocalSites:
    """Serves each artifact it is handed, exactly, with its own _headers."""

    def __init__(self, stack: ExitStack) -> None:
        self._stack = stack
        self.artifacts: list[WebsiteArtifact] = []
        self.urls: list[str] = []

    def serve(self, artifact: WebsiteArtifact) -> str:
        url = self._stack.enter_context(serve_artifact(artifact))
        self.artifacts.append(artifact)
        self.urls.append(url)
        return url


class LocalPreviewPublisher(PreviewPublisher):
    def __init__(self, sites: LocalSites) -> None:
        self.sites = sites

    def publish_preview(self, *, branch, artifact):
        url = self.sites.serve(artifact)
        return PreviewDeployment(deployment_id=f"preview-{len(self.sites.urls)}", url=f"{url}/")

    def retire_preview(self, *, branch, deployment_id):
        pass


class LocalProductionPublisher(WebsitePublisher):
    def __init__(self, sites: LocalSites) -> None:
        self.sites = sites

    def publish(self, *, site_id, artifact):
        url = self.sites.serve(artifact)
        return PublishedSite(deployment_id=f"live-{len(self.sites.urls)}", url=f"{url}/", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


def seed(password: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    Base.metadata.create_all(engine)
    config = PROFILE["config"]()
    with Session(engine) as session:
        tenant = Tenant(name="R5 E2E tenant")
        session.add(tenant)
        session.flush()
        user = User(email="r5-operator@example.com", hashed_password=hash_password(password))
        session.add(user)
        session.flush()
        session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
        business = Business(
            tenant_id=tenant.id,
            name=config.business_profile.name,
            slug=config.business_profile.slug,
            vertical=config.business_profile.industry,
            raw_description="Fictional R5 E2E business.",
            status=BusinessStatus.DRAFT,
            config=config.model_dump(mode="json"),
        )
        session.add(business)
        session.commit()
        return tenant.id, business.id, user.email


def start_api() -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("the local GWA API did not start")


def run_worker() -> dict:
    """One job on a SEPARATE worker process with a minimal environment."""
    home = WORK_ROOT / "worker-home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "PYTHONPATH": str(API_ROOT),
        "GWA_API_BASE_URL": API,
        "GWA_WORKER_TOKEN": WORKER_TOKEN,
        "GWA_WORKER_ISOLATION": ARGS.isolation,
        "GWA_WORKER_ID": "r5-e2e",
        "GWA_DEPENDENCY_ROOT": str(home / "deps"),
        # Where the worker image ships Chromium for Visual QA (not a secret).
        "PLAYWRIGHT_BROWSERS_PATH": os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH", str(Path(os.environ.get("HOME", "/root")) / ".cache" / "ms-playwright")
        ),
    }
    started = time.monotonic()
    command = [sys.executable, "-m", "app.worker", "--once"]
    if ARGS.measure:
        command = ["/usr/bin/time", "-v", *command]
    proc = subprocess.run(  # noqa: S603
        command,
        cwd=home,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    peak = next(
        (line.split(":")[-1].strip() for line in proc.stderr.splitlines() if "Maximum resident set size" in line), None
    )
    return {
        "exit": proc.returncode,
        "seconds": round(time.monotonic() - started, 1),
        # largest single process's peak RSS (kB): a lower bound for the job
        "peak_rss_kb": int(peak) if peak else None,
        "log_tail": proc.stderr[-1500:],
    }


def variant_zip(original: bytes, rel: str, old: str, new: str) -> bytes:
    """The same export with ONE visible copy change (a second version)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out, zipfile.ZipFile(io.BytesIO(original)) as src:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == rel:
                if old.encode() not in data:
                    raise SystemExit(f"{old!r} not in {rel}")
                data = data.replace(old.encode(), new.encode(), 1)
            out.writestr(info, data)
    return buffer.getvalue()


def main() -> None:  # noqa: C901 — a linear E2E script
    from playwright.sync_api import sync_playwright

    settings.supervised_source_imports_enabled = True
    settings.generation_worker_token_sha256 = hash_worker_token(WORKER_TOKEN)
    settings.generation_worker_signing_key = secrets.token_hex(32)
    storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=E2E_DIR / "private"))
    password = secrets.token_urlsafe(24)
    tenant_id, business_id, email = seed(password)
    report: dict = {"fixture": ARGS.fixture, "isolation": ARGS.isolation}

    with ExitStack() as stack:
        sites = LocalSites(stack)
        app.dependency_overrides[get_private_artifact_storage] = lambda: storage
        app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(root_dir=E2E_DIR / "public")
        app.dependency_overrides[get_website_publisher] = lambda: LocalProductionPublisher(sites)
        app.dependency_overrides[get_preview_publisher] = lambda: LocalPreviewPublisher(sites)
        app.dependency_overrides[get_optional_preview_publisher] = lambda: LocalPreviewPublisher(sites)
        api = start_api()
        client = stack.enter_context(httpx.Client(base_url=API, timeout=600))
        login = client.post("/auth/login", json={"email": email, "password": password})
        check("operator_logs_in", login.status_code == 200, login.status_code)
        headers = {"X-Tenant-Id": str(tenant_id), "X-CSRF-Token": login.json()["csrf_token"]}
        base = f"/businesses/{business_id}/source-imports"
        drafts = f"/businesses/{business_id}/website-drafts"

        capability = client.get(f"{base}/capability", headers=headers).json()
        check("capability_enabled_with_worker", capability["enabled"] and capability["worker_configured"], capability)

        def import_zip(data: bytes, name: str) -> dict:
            response = client.post(base, headers=headers, files={"file": (name, data, "application/zip")})
            if response.status_code != 201:
                raise SystemExit(f"import failed: {response.status_code} {response.text[:500]}")
            return response.json()

        def review_and_build(body: dict) -> dict:
            for finding in body["open_reviews"]:
                decided = client.post(
                    f"{base}/{body['id']}/decisions",
                    headers=headers,
                    json={
                        "finding_id": finding,
                        "decision": "approved",
                        "rationale": "Reviewed by the operator (E2E).",
                    },
                )
                if decided.status_code != 200:
                    raise SystemExit(f"decision failed: {decided.text[:500]}")
                body = decided.json()
            built = client.post(f"{base}/{body['id']}/build", headers=headers)
            if built.status_code != 202:
                raise SystemExit(f"build failed to start: {built.text[:500]}")
            worker = run_worker()
            return {"state": client.get(f"{base}/{body['id']}", headers=headers).json(), "worker": worker}

        # --- A: the unchanged original export -------------------------------------------------
        if ARGS.fixture == "lumen-physio":
            original = zip_directory(LUMEN_FIXTURE, WORK_ROOT / "lumen-physio.zip").read_bytes()
        else:
            original = ARGS.zip.read_bytes()
        sha_zip = hashlib.sha256(original).hexdigest()
        imported = import_zip(original, f"{ARGS.fixture}.zip")
        keys = ("status", "stage", "zip_sha256", "plan_sha256", "adapter", "supportability", "open_reviews")
        report["import_a"] = {k: imported[k] for k in keys}
        check("snapshot_identity_is_the_zip_sha", imported["zip_sha256"] == sha_zip)
        check("inspection_supported", imported["status"] in ("ready_to_build", "needs_review"), imported["status"])
        snapshot_key = f"source-snapshots/{tenant_id}/{business_id}/{sha_zip}.zip"
        check("immutable_snapshot_stored_byte_identical", storage.load(snapshot_key) == original)
        run_a = review_and_build(imported)
        state_a = run_a["state"]
        report["build_a"] = {
            "worker": run_a["worker"],
            "stage": state_a["stage"],
            "job": state_a["job_status"],
            "draft": state_a["draft"],
            "error": state_a["error"],
        }
        check("worker_process_exited_cleanly", run_a["worker"]["exit"] == 0, run_a["worker"])
        check("intake_accepted_artifact_a", state_a["stage"] == "preview_ready", state_a["error"] or state_a["stage"])
        draft_a = state_a["draft"] or {}
        check("qa_evidence_current_and_passed_a", draft_a.get("visual_qa_current") and draft_a.get("visual_qa_passed"))
        if state_a["stage"] != "preview_ready":
            finish(report)
            raise SystemExit(1)
        sha_a = draft_a.get("artifact_sha256")

        refused = client.post(f"{drafts}/{draft_a['id']}/publish", headers=headers)
        check("publish_refused_before_approval", refused.status_code == 409, refused.status_code)
        preview = client.post(f"{drafts}/{draft_a['id']}/preview", headers=headers).json()
        preview_url = preview["preview_url"].rstrip("/")
        check("preview_serves_the_exact_artifact", artifact_sha256(sites.artifacts[-1]) == sha_a)
        still = client.get(f"{base}/{imported['id']}", headers=headers).json()
        check("preview_does_not_approve", still["stage"] == "preview_ready")

        # --- Browser on the REAL preview ---------------------------------------------------------
        mapping = state_a["inspection"]["forms"][0]
        expected_details: list[dict] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script(
                "window.__csp=[];document.addEventListener('securitypolicyviolation',"
                "e=>window.__csp.push(e.violatedDirective+' '+e.blockedURI));"
            )
            page = ctx.new_page()
            response = page.goto(preview_url + "/", wait_until="networkidle")
            page.wait_for_timeout(1500)
            csp = response.headers.get("content-security-policy", "") if response else ""
            check("preview_loads_with_production_headers", response is not None and response.status == 200 and csp)
            banner = page.locator("#gwa-consent-banner")
            check("consent_banner_in_site_language", banner.is_visible() and PROFILE["consent"] in banner.inner_text())
            page.click("#gwa-consent-reject")
            if PROFILE["videos"]:
                height = page.evaluate("document.documentElement.scrollHeight")
                for y in range(0, height, 600):
                    page.evaluate(f"window.scrollTo(0, {y})")
                    page.wait_for_timeout(100)
                page.wait_for_timeout(1500)
                videos = page.evaluate(
                    "[...document.querySelectorAll('video')].map(v=>({src:v.currentSrc.slice(0,5),ready:v.readyState}))"
                )
                ok = len(videos) == 6 and all(v["src"] == "blob:" and v["ready"] >= 2 for v in videos)
                check("all_six_videos_play", ok, videos)
            seo = page.evaluate(
                "() => ({og: document.querySelector('meta[property=\"og:image\"]')?.content,"
                " canonical: document.querySelector('link[rel=\"canonical\"]')?.href,"
                " ld: document.querySelectorAll('script[type=\"application/ld+json\"]').length})"
            )
            origin = state_a["site_origin"]
            seo_ok = seo["og"] == f"{origin}/og-image.jpg" and seo["canonical"] == f"{origin}/" and seo["ld"] >= 1
            check("seo_og_canonical_jsonld", seo_ok, seo)
            for slug in ("privacy", "terms", "cookies"):
                legal = ctx.new_page()
                answer = legal.goto(f"{preview_url}/{slug}", wait_until="networkidle")
                check(
                    f"legal_route_{slug}",
                    answer is not None and answer.status == 200 and legal.locator("h1").count() == 1,
                )
                legal.close()
            form = 'form[data-gwa-lead-form="lead-1"]'
            page.locator(form).scroll_into_view_if_needed()
            page.wait_for_timeout(2500)  # the Lead API's spam-timing minimum
            for field in mapping["fields"]:
                locator = page.locator(f'{form} [name="{field["name"]}"]')
                if field["element"] == "select":
                    option = locator.locator("option").nth(1)
                    locator.select_option(option.get_attribute("value"))
                    shown = option.inner_text().strip()
                elif locator.get_attribute("type") == "checkbox":
                    locator.check()
                    shown = "true"
                else:
                    shown = PROFILE["values"].get(field["role"], PROFILE["values"]["detail"])
                    locator.fill(shown)
                if field["role"] in ("service", "detail"):
                    expected_details.append({"key": field["key"], "label": field["label"], "value": shown})
            page.locator(f"{form} [type=submit]").click()
            page.wait_for_selector(PROFILE["success"], timeout=15000)
            violations = page.evaluate("window.__csp")
            check("no_csp_violations_on_preview", not violations, violations)
            browser.close()
        with Session(engine) as session:
            leads = list(session.scalars(select(Lead).where(Lead.business_id == business_id)).all())
        stored_details = leads[0].details if leads else None
        check("lead_stored_once_with_all_details", len(leads) == 1 and stored_details == expected_details,
              {"leads": len(leads), "details": stored_details})  # fmt: skip
        listed = client.get(f"/businesses/{business_id}/leads", headers=headers).json()
        check("studio_sees_the_lead", len(listed) == 1 and listed[0]["details"] == expected_details)

        approved = client.post(f"{drafts}/{draft_a['id']}/approve", headers=headers)
        check("artifact_a_approved", approved.status_code == 200, approved.text[:200])
        published = client.post(f"{drafts}/{draft_a['id']}/publish", headers=headers)
        check("artifact_a_published", published.status_code == 200, published.text[:200])
        live_a = sites.artifacts[-1]
        same = artifact_sha256(live_a) == sha_a and live_a.files == sites.artifacts[0].files
        check("previewed_approved_published_are_the_same_bytes", same)
        served = httpx.get(f"{sites.urls[-1]}/index.html").content
        check("live_serves_the_published_bytes", served == live_a.files["index.html"])

        # --- B: a second version: review gate, build, publish ----------------------------
        rel, old, new = PROFILE["edit"]
        variant = import_zip(variant_zip(original, rel, old, new), "variant.zip")
        report["variant"] = {k: variant[k] for k in ("status", "zip_sha256", "plan_sha256", "open_reviews")}
        if ARGS.fixture == "nexo-reformas":
            # A changed export loses the reviewed overlay (pinned to the original's
            # SHA-256): its server-id form finding is an open BLOCKER, never
            # approvable — so version B here is a rebuild of the unchanged export.
            blocked = variant["status"] == "blocked" and any(
                f["code"] == "form_displays_server_identifier" and f["open"] for f in variant["inspection"]["findings"]
            )
            check("changed_export_without_reviewed_fix_is_blocked", blocked, variant["status"])
            refused_build = client.post(f"{base}/{variant['id']}/build", headers=headers)
            check("blocked_export_cannot_build", refused_build.status_code == 409, refused_build.status_code)
            imported_b = import_zip(original, f"{ARGS.fixture}-rebuild.zip")
        else:
            imported_b = variant
        report["import_b"] = {k: imported_b[k] for k in ("status", "zip_sha256", "plan_sha256", "open_reviews")}
        check(
            "second_version_inspected", imported_b["status"] in ("ready_to_build", "needs_review"), imported_b["status"]
        )
        run_b = review_and_build(imported_b)
        state_b = run_b["state"]
        report["build_b"] = {"worker": run_b["worker"], "stage": state_b["stage"], "error": state_b["error"]}
        check("intake_accepted_artifact_b", state_b["stage"] == "preview_ready", state_b["error"] or state_b["stage"])
        draft_b = state_b["draft"] or {}
        sha_b = draft_b.get("artifact_sha256")
        client.post(f"{drafts}/{draft_b['id']}/approve", headers=headers)
        published_b = client.post(f"{drafts}/{draft_b['id']}/publish", headers=headers)
        ok_b = published_b.status_code == 200 and artifact_sha256(sites.artifacts[-1]) == sha_b and sha_b != sha_a
        check("artifact_b_published", ok_b, published_b.text[:200])

        # --- Rollback to A --------------------------------------------------------------------
        versions = client.get(f"/businesses/{business_id}/website/versions", headers=headers).json()
        previous = [v for v in versions if not v["is_current"]]
        rolled = client.post(
            f"/businesses/{business_id}/website/versions/{previous[0]['id']}/rollback", headers=headers
        )
        check("rollback_succeeds", rolled.status_code == 200, rolled.text[:200])
        check("rollback_restores_exact_bytes_of_a", artifact_sha256(sites.artifacts[-1]) == sha_a)
        unchanged = storage.load(snapshot_key) == original and hashlib.sha256(original).hexdigest() == sha_zip
        check("original_snapshot_unchanged", unchanged)

        report["identities"] = {
            "zip_a": sha_zip,
            "plan_a": imported["plan_sha256"],
            "artifact_a": sha_a,
            "zip_b": imported_b["zip_sha256"],
            "plan_b": imported_b["plan_sha256"],
            "artifact_b": sha_b,
        }
        api.should_exit = True

    finish(report)


def finish(report: dict) -> None:
    report["passed"] = [r["test"] for r in RESULTS if r["passed"]]
    report["failed"] = [r for r in RESULTS if not r["passed"]]
    out = WORK_ROOT / "r5-e2e-report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"failed": report["failed"]}, indent=1, default=str))
    print(f"{len(report['passed'])} passed, {len(report['failed'])} failed")


if __name__ == "__main__":
    main()
