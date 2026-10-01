"""R5.1 — negative, crash and health checks against the REAL worker image.

    uv run python scripts/r5_1_container_checks.py --image gwa-build-worker:r5-1 \
        --work-root /tmp/gwa-r51/checks

A throwaway local API (uvicorn, SQLite, local private storage — the same
isolation preamble as scripts/r5_product_e2e.py) and the worker container
(host network, only so it can reach 127.0.0.1). No provider, no Cloudflare,
no production credential: every "secret" below is a random string made up
for this run, injected to prove the worker REFUSES it.

Checks:
- startup refusals: no token, inherited DATABASE_URL / Cloudflare / R2 /
  provider / Resend / n8n keys, missing bun, missing Chromium, bad API URL,
  concurrency 2;
- health: 200 only once preflight passed; a misconfigured container never
  serves it; SIGTERM on an idle worker exits 0 promptly;
- a REAL build whose own vite.config.ts reports the environment it got:
  no worker token, no GWA_* variable, no credential-shaped variable;
- SIGTERM in the middle of a real build: the attempt is released, the job
  requeued, the container leaves no job workspace, a fresh container
  finishes it as attempt 2 and exactly one artifact is stored;
- SIGKILL in the middle of a real build: the lease expires, attempt 2
  succeeds, exactly one artifact is stored;
- the worker token is refused by every operator endpoint and by the
  snapshot endpoint.
"""

import argparse
import os
import sys
from pathlib import Path

_PARSER = argparse.ArgumentParser()
_PARSER.add_argument("--image", required=True)
_PARSER.add_argument("--work-root", type=Path, required=True)
ARGS = _PARSER.parse_args()
WORK_ROOT = ARGS.work_root.resolve()
E2E_DIR = WORK_ROOT / "api"
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
_DB = E2E_DIR / "checks.db"
_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["PUBLIC_API_BASE_URL"] = "http://127.0.0.1:8766"
os.chdir(E2E_DIR)  # no .env here
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import json  # noqa: E402
import secrets  # noqa: E402
import shutil  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from collections.abc import Callable  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402

_LEAKED = [n.lower() for n in _PROVIDER_ENV[:-2] if getattr(settings, n.lower(), None)]
if _LEAKED or str(E2E_DIR) not in settings.database_url:
    sys.exit(f"refusing to run: non-isolated settings {_LEAKED or settings.database_url!r}")

from app.creative.source_adapter.fixtures import lumen_physio_business_config, zip_directory  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models.business import Business  # noqa: E402
from app.db.models.generation_job import GenerationJob  # noqa: E402
from app.db.models.source_import import SourceImport  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_access import TenantAccess  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.dependencies import engine, get_private_artifact_storage, get_storage_provider  # noqa: E402
from app.domain.enums import BusinessStatus, UserRole  # noqa: E402
from app.main import app  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.storage import LocalStorageProvider  # noqa: E402
from app.storage.private import PrivateArtifactStorage  # noqa: E402
from app.worker.auth import hash_worker_token  # noqa: E402

API_PORT = 8766
API = f"http://127.0.0.1:{API_PORT}"
HEALTH_PORT = 18766
WORKER_TOKEN = secrets.token_hex(32)  # this run only
FAKE_SECRET = "fake-" + secrets.token_hex(12)  # injected to prove refusal; never a real credential
LUMEN = API_ROOT / "tests" / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
PRIVATE = E2E_DIR / "private"
RESULTS: list[dict] = []


def check(name: str, passed: object, detail: object = "") -> None:
    RESULTS.append({"test": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name + (f" — {detail}" if detail and not passed else ""), flush=True)


def docker(*args: str, token: bool = True, timeout: int = 1800) -> subprocess.CompletedProcess:
    """`-e GWA_WORKER_TOKEN` (no value) forwards it from THIS environment;
    with token=False it is simply not set in the container."""
    env = {"PATH": os.environ["PATH"], **({"GWA_WORKER_TOKEN": WORKER_TOKEN} if token else {})}
    return subprocess.run(["docker", *args], env=env, capture_output=True, text=True, timeout=timeout)  # noqa: S603, S607


def worker_args(*extra_env: str, name: str | None = None, detach: bool = False, api: bool = True) -> list[str]:
    args = ["run", "--network", "host", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    args += ["--name", name] if name else ["--rm"]
    args += ["-d"] if detach else []
    args += ["-e", "GWA_WORKER_TOKEN", "-e", "GWA_WORKER_ID=r5-1-checks"]
    for item in ([f"GWA_API_BASE_URL={API}"] if api else []) + list(extra_env):
        args += ["-e", item]
    return args


def run_worker_once() -> subprocess.CompletedProcess:
    return docker(*worker_args(), ARGS.image, "--once")


def seed(password: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    Base.metadata.create_all(engine)
    config = lumen_physio_business_config()
    with Session(engine) as session:
        tenant = Tenant(name="R5.1 checks")
        session.add(tenant)
        session.flush()
        user = User(email="r51-operator@example.com", hashed_password=hash_password(password))
        session.add(user)
        session.flush()
        session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
        business = Business(
            tenant_id=tenant.id,
            name=config.business_profile.name,
            slug=config.business_profile.slug,
            vertical=config.business_profile.industry,
            raw_description="Fictional R5.1 business.",
            status=BusinessStatus.DRAFT,
            config=config.model_dump(mode="json"),
        )
        session.add(business)
        session.commit()
        return tenant.id, business.id, user.email


def lumen_zip(name: str, edits: dict[str, str] | None = None) -> bytes:
    source = WORK_ROOT / "sources" / name / "lumen-physio"
    shutil.rmtree(source.parent, ignore_errors=True)
    shutil.copytree(LUMEN, source)
    for rel, content in (edits or {}).items():
        (source / rel).write_text(content, encoding="utf-8")
    return zip_directory(source, WORK_ROOT / "sources" / f"{name}.zip").read_bytes()


def job_row(job_id: uuid.UUID) -> GenerationJob:
    with Session(engine) as session:
        job = session.get(GenerationJob, job_id)
        assert job is not None
        session.expunge(job)
        return job


def stored_artifacts(draft_id: uuid.UUID | None) -> int:
    """Artifact objects stored for this draft (its key is write-once)."""
    marker = draft_id.hex if draft_id is not None else "-"
    return sum(1 for path in (PRIVATE / "website-drafts").rglob("*") if path.is_file() and marker in str(path))


def wait_for(predicate: Callable[[], bool], timeout: float, interval: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def startup_refusals() -> None:
    cases = [
        ("database_url_refuses_startup", [f"DATABASE_URL=postgresql://u:{FAKE_SECRET}@db.internal/x"], "DATABASE_URL"),
        ("cloudflare_token_refuses_startup", [f"CLOUDFLARE_API_TOKEN={FAKE_SECRET}"], "CLOUDFLARE_API_TOKEN"),
        ("r2_secret_refuses_startup", [f"R2_PRIVATE_SECRET_ACCESS_KEY={FAKE_SECRET}"], "R2_PRIVATE_SECRET_ACCESS_KEY"),
        ("provider_keys_refuse_startup", [f"ANTHROPIC_API_KEY={FAKE_SECRET}", f"OPENAI_API_KEY={FAKE_SECRET}"],
         "OPENAI_API_KEY"),
        ("resend_and_n8n_refuse_startup", [f"RESEND_API_KEY={FAKE_SECRET}", f"N8N_API_KEY={FAKE_SECRET}"],
         "RESEND_API_KEY"),
        ("concurrency_two_refuses_startup", ["GWA_WORKER_CONCURRENCY=2"], "concurrency"),
        ("missing_chromium_refuses_startup", ["PLAYWRIGHT_BROWSERS_PATH=/nonexistent"], "chromium: cannot launch"),
    ]  # fmt: skip
    for name, extra, expect in cases:
        proc = docker(*worker_args(*extra), ARGS.image, "--once")
        output = proc.stdout + proc.stderr
        ok = proc.returncode == 78 and expect in output and FAKE_SECRET not in output and WORKER_TOKEN not in output
        check(name, ok, {"exit": proc.returncode, "tail": output[-300:]})

    proc = docker(*worker_args(), ARGS.image, "--once", token=False)
    output = proc.stdout + proc.stderr
    check("missing_worker_token_refuses_startup", proc.returncode == 78 and "worker_token" in output, output[-200:])
    proc = docker(*worker_args("GWA_API_BASE_URL=http://api.example.com", api=False), ARGS.image, "--once")
    check("non_https_api_url_refuses_startup", proc.returncode == 78 and "https" in proc.stdout + proc.stderr)
    proc = docker(*worker_args(), "-v", "/dev/null:/usr/local/bin/bun:ro", ARGS.image, "--once")
    output = proc.stdout + proc.stderr
    refused_bun = "bun:" in output or '"bun": false' in output  # selftest or preflight, whichever runs first
    check("missing_bun_refuses_startup", proc.returncode == 78 and refused_bun, {"exit": proc.returncode})


def health_and_idle_stop() -> None:
    name = f"gwa-r51-health-{secrets.token_hex(3)}"
    docker(*worker_args(f"PORT={HEALTH_PORT}", name=name, detach=True), ARGS.image)
    seen: list[int] = []

    def ready() -> bool:
        try:
            status = httpx.get(f"http://127.0.0.1:{HEALTH_PORT}/health", timeout=2).status_code
        except httpx.HTTPError:
            return False
        seen.append(status)
        return status == 200

    check("health_200_after_preflight", wait_for(ready, 90), seen[-3:])
    body = httpx.get(f"http://127.0.0.1:{HEALTH_PORT}/health", timeout=2).text
    check("health_body_carries_no_secret_or_url", WORKER_TOKEN not in body and "http" not in body, body)
    started = time.monotonic()
    docker("stop", "-t", "30", name)
    stopped = round(time.monotonic() - started, 1)
    code = docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip()
    check("idle_worker_stops_on_sigterm", code == "0" and stopped < 15, {"exit": code, "seconds": stopped})
    docker("rm", "-f", name)

    bad = f"gwa-r51-bad-{secrets.token_hex(3)}"
    docker(*worker_args(f"PORT={HEALTH_PORT}", f"DATABASE_URL={FAKE_SECRET}", name=bad, detach=True), ARGS.image)
    exited = wait_for(lambda: docker("inspect", "-f", "{{.State.Running}}", bad).stdout.strip() == "false", 90)
    code = docker("inspect", "-f", "{{.State.ExitCode}}", bad).stdout.strip()
    try:
        httpx.get(f"http://127.0.0.1:{HEALTH_PORT}/health", timeout=2)
        served = True
    except httpx.HTTPError:
        served = False
    check("misconfigured_worker_never_reports_healthy", exited and code == "78" and not served, {"exit": code})
    docker("rm", "-f", bad)


def main() -> None:  # noqa: C901, PLR0915 — a linear check script
    settings.supervised_source_imports_enabled = True
    settings.generation_worker_token_sha256 = hash_worker_token(WORKER_TOKEN)
    settings.generation_worker_signing_key = secrets.token_hex(32)
    storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=PRIVATE))
    app.dependency_overrides[get_private_artifact_storage] = lambda: storage
    app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(root_dir=E2E_DIR / "public")
    password = secrets.token_urlsafe(24)
    tenant_id, business_id, email = seed(password)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    wait_for(lambda: server.started, 10, 0.05)
    client = httpx.Client(base_url=API, timeout=600)
    login = client.post("/auth/login", json={"email": email, "password": password})
    headers = {"X-Tenant-Id": str(tenant_id), "X-CSRF-Token": login.json()["csrf_token"]}
    base = f"/businesses/{business_id}/source-imports"

    def import_and_queue(data: bytes, name: str) -> tuple[dict, uuid.UUID]:
        created = client.post(base, headers=headers, files={"file": (name, data, "application/zip")})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "ready_to_build", body["status"]
        queued = client.post(f"{base}/{body['id']}/build", headers=headers)
        assert queued.status_code == 202, queued.text
        found: list[uuid.UUID] = []

        def committed() -> bool:  # the API commits in dependency teardown, after its response
            with Session(engine) as session:
                job_id = session.scalar(select(SourceImport.job_id).where(SourceImport.id == uuid.UUID(body["id"])))
            found.extend([job_id] if job_id else [])
            return bool(found)

        assert wait_for(committed, 10, 0.1)
        job_id = found[0]
        return body, job_id

    # --- WS16: a near-limit ZIP over real HTTP; an over-limit one refused unread ---------
    big = WORK_ROOT / "sources" / "big" / "lumen-physio"
    shutil.rmtree(big.parent, ignore_errors=True)
    shutil.copytree(LUMEN, big)
    for index in range(2):  # incompressible media, under the 64 MB per-file snapshot limit
        (big / "public" / f"filler-{index}.bin").write_bytes(os.urandom(47 * 1024 * 1024))
    big_zip = zip_directory(big, WORK_ROOT / "sources" / "big.zip").read_bytes()
    started = time.monotonic()
    near = client.post(base, headers=headers, files={"file": ("big.zip", big_zip, "application/zip")})
    check(
        "near_limit_upload_reaches_the_api_and_is_inspected",
        near.status_code == 201 and len(big_zip) < settings.supervised_source_max_bytes,
        {"status": near.status_code, "bytes": len(big_zip), "seconds": round(time.monotonic() - started, 1)},
    )
    RESULTS[-1]["upload_mib"] = round(len(big_zip) / 1024**2, 1)
    RESULTS[-1]["seconds"] = round(time.monotonic() - started, 1)
    over = settings.supervised_source_max_bytes + 4 * 1024 * 1024
    started = time.monotonic()
    cookie = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    request = (
        f"POST {base} HTTP/1.1\r\nHost: 127.0.0.1:{API_PORT}\r\nX-Tenant-Id: {tenant_id}\r\n"
        f"X-CSRF-Token: {headers['X-CSRF-Token']}\r\nCookie: {cookie}\r\n"
        f"Content-Type: multipart/form-data; boundary=x\r\nContent-Length: {over}\r\n\r\n--x\r\n"
    )  # declares > the limit, sends almost nothing: the API must answer without waiting for the body
    with socket.create_connection(("127.0.0.1", API_PORT), timeout=10) as raw:
        raw.sendall(request.encode())
        status_line = raw.recv(4096).split(b"\r\n", 1)[0].decode()

    class _Refused:
        status_code = int(status_line.split()[1]) if len(status_line.split()) > 1 else 0

    refused = _Refused()
    check(
        "over_limit_upload_refused_from_content_length",
        refused.status_code == 413 and time.monotonic() - started < 5,
        {"status": refused.status_code, "seconds": round(time.monotonic() - started, 2)},
    )
    with Session(engine) as session:  # the near-limit import is not used further
        session.query(SourceImport).filter(SourceImport.id == uuid.UUID(near.json()["id"])).delete()
        session.commit()

    startup_refusals()
    health_and_idle_stop()

    # --- The export's own build code reports the environment it received ----------------
    config = (LUMEN / "vite.config.ts").read_text(encoding="utf-8")
    probe = (
        "\nconst __gwaEnv = process.env;\n"
        "throw new Error('GWA_ENV_PROBE[' + Object.keys(__gwaEnv).sort().join(',') + ']HEX64=' +"
        " Object.values(__gwaEnv).some((v) => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v)));\n"
    )
    _, probe_job = import_and_queue(lumen_zip("probe", {"vite.config.ts": config + probe}), "probe.zip")
    run_worker_once()
    error = job_row(probe_job).error or ""
    names = error.split("GWA_ENV_PROBE[", 1)[1].split("]", 1)[0].split(",") if "GWA_ENV_PROBE[" in error else []
    bad = [n for n in names if n.startswith("GWA_") or any(p in n for p in ("TOKEN", "SECRET", "PASSWORD", "_KEY"))]
    check(
        "real_build_sees_no_worker_token_or_secret",
        bool(names) and not bad and "HEX64=false" in error and WORKER_TOKEN not in error,
        {"names": names, "bad": bad},
    )
    RESULTS[-1]["build_environment_names"] = names

    # --- SIGTERM in the middle of a real build ---------------------------------------------
    body, term_job = import_and_queue(lumen_zip("term", {"README.md": "sigterm"}), "term.zip")
    name = f"gwa-r51-term-{secrets.token_hex(3)}"
    docker(*worker_args(name=name, detach=True), ARGS.image)
    running = wait_for(lambda: "job started" in docker("logs", name).stderr, 120)
    time.sleep(3)  # well inside install/build
    started = time.monotonic()
    docker("stop", "-t", "30", name)
    stop_seconds = round(time.monotonic() - started, 1)
    logs = docker("logs", name).stderr
    leftovers = [line for line in docker("diff", name).stdout.splitlines() if "/tmp/gwa-worker/job-" in line]
    code = docker("inspect", "-f", "{{.State.ExitCode}}", name).stdout.strip()
    docker("rm", "-f", name)
    job = job_row(term_job)
    check(
        "sigterm_mid_build_releases_and_requeues",
        running and code == "0" and job.status.value == "queued" and job.attempts == 1 and "report=accepted" in logs,
        {"exit": code, "status": job.status.value, "attempts": job.attempts, "logs": logs[-600:]},
    )
    check("sigterm_leaves_no_job_workspace", not leftovers, leftovers[:5])
    check("sigterm_stop_is_prompt", stop_seconds < 20, stop_seconds)
    run_worker_once()
    job = job_row(term_job)
    final = client.get(f"{base}/{body['id']}", headers=headers).json()
    check(
        "requeued_job_finishes_as_attempt_two_with_one_artifact",
        job.status.value == "succeeded" and job.attempts == 2 and stored_artifacts(job.draft_id) == 1
        and final["stage"] == "preview_ready",
        {"status": job.status.value, "attempts": job.attempts, "stored": stored_artifacts(job.draft_id)},
    )  # fmt: skip

    # --- SIGKILL in the middle of a real build (crash: nothing reported) -----------------
    body, kill_job = import_and_queue(lumen_zip("kill", {"README.md": "sigkill"}), "kill.zip")
    name = f"gwa-r51-kill-{secrets.token_hex(3)}"
    docker(*worker_args(name=name, detach=True), ARGS.image)
    wait_for(lambda: "job started" in docker("logs", name).stderr, 120)
    time.sleep(3)
    docker("kill", name)
    docker("rm", "-f", name)
    job = job_row(kill_job)
    check(
        "sigkill_leaves_the_job_running_under_its_lease",
        job.status.value == "running" and job.attempts == 1,
        {"status": job.status.value, "attempts": job.attempts},
    )
    with Session(engine) as session:  # let the lease pass (instead of waiting 15 minutes)
        row = session.get(GenerationJob, kill_job)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    run_worker_once()
    job = job_row(kill_job)
    final = client.get(f"{base}/{body['id']}", headers=headers).json()
    check(
        "crashed_job_recovers_as_attempt_two_with_one_artifact",
        job.status.value == "succeeded" and job.attempts == 2 and stored_artifacts(job.draft_id) == 1
        and final["stage"] == "preview_ready",
        {"status": job.status.value, "attempts": job.attempts, "stored": stored_artifacts(job.draft_id)},
    )  # fmt: skip

    # --- The worker credential has no operator authority -----------------------------------
    draft = final["draft"]["id"]
    targets = [
        ("GET", base),
        ("POST", f"{base}/{body['id']}/build"),
        ("POST", f"/businesses/{business_id}/website-drafts/{draft}/approve"),
        ("POST", f"/businesses/{business_id}/website-drafts/{draft}/publish"),
        ("GET", f"/businesses/{business_id}/leads"),
        ("GET", f"/internal/generation-worker/jobs/{kill_job}/source"),
    ]
    refused = {}
    for method, url in targets:
        with httpx.Client(base_url=API, cookies={settings.session_cookie_name: WORKER_TOKEN}) as as_worker:
            response = as_worker.request(
                method, url, headers={"Authorization": f"Bearer {WORKER_TOKEN}", "X-Tenant-Id": str(tenant_id)}
            )
        refused[f"{method} {url}"] = response.status_code
    check("worker_token_refused_by_operator_and_source_endpoints", set(refused.values()) == {401}, refused)

    server.should_exit = True
    out = WORK_ROOT / "r5-1-container-checks.json"
    out.write_text(json.dumps(RESULTS, indent=2, default=str), encoding="utf-8")
    failed = [r for r in RESULTS if not r["passed"]]
    print(f"{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
