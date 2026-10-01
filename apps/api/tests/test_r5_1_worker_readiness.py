# ruff: noqa: F811 — pytest fixtures imported from tests/test_r5_source_imports.py
"""R5.1 — the supervised build worker, made deployment-ready.

Secret denylist and startup preflight, the child-process environment
allowlist (proved against a REAL Vite build and a REAL Chromium), per-job
workspace cleanup on success/failure/timeout/SIGTERM, lease expiry and
SIGTERM release with bounded requeue, duplicate-result safety, the worker
credential's (lack of) authority, conservative concurrency and the health
endpoint. Fixtures and helpers are shared with tests/test_r5_source_imports.py.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings, settings
from app.creative import generation_jobs as jobs
from app.creative.frontend_engine.sandbox import SandboxError, SandboxLimits, SupervisedProcessRunner
from app.creative.source_adapter import static_build
from app.db.models.generation_job import GenerationJob
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.source_import import SourceImport
from app.db.models.website_draft import WebsiteDraft
from app.dependencies import get_current_tenant_id, get_current_user
from app.domain.enums import GenerationFailureKind, GenerationJobStatus, SourceImportStatus, WebsiteDraftStatus
from app.main import app
from app.worker import __main__ as worker_main
from app.worker import intake, preflight
from app.worker.protocol import ExecutionRequest, ExecutionResult
from app.worker.source_executor import execute_source_adaptation
from tests.test_r5_source_imports import (  # noqa: F401 — shared fixtures
    FIXTURE,
    WORKER_TOKEN,
    Env,
    _import_and_build,
    _submit,
    _variant_zip,
    built,
    env,
)

GOOD_TOKEN = "w" * 48
MARKER = "r5-1-marker-" + uuid.uuid4().hex
API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _worker_process_protection_stubbed(monkeypatch):
    """R5.1.2: these tests drive the worker IN the pytest process; the real
    non-dumpable protection is exercised in subprocesses by
    tests/test_r5_1_2_worker_proc_isolation.py (never on pytest itself)."""
    from app.worker import process_protection

    monkeypatch.setattr(process_protection, "make_non_dumpable", lambda: None)
    monkeypatch.setattr(process_protection, "is_non_dumpable", lambda: True)

def _base_environ(**extra: str) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": "/home/worker",
        "GWA_API_BASE_URL": "https://api.example.com",
        "GWA_WORKER_TOKEN": GOOD_TOKEN,
        "GWA_WORKER_ISOLATION": "supervised-process",
        "RAILWAY_SERVICE_NAME": "gwa-build-worker",
        "PORT": "8080",
        **extra,
    }


@pytest.fixture(autouse=True)
def _no_dotenv_here(tmp_path, monkeypatch):
    """Preflight refuses a .env in the working directory (apps/api has one)."""
    monkeypatch.chdir(tmp_path)


def _preflight(tmp_path: Path, environ: dict[str, str], **kwargs) -> preflight.PreflightReport:
    return preflight.run_preflight(
        environ=environ, isolation="supervised-process", work_root=tmp_path / "work", launch_chromium=False, **kwargs
    )


def _failed(report: preflight.PreflightReport) -> set[str]:
    return {check.name for check in report.checks if not check.ok}


def _claimed_request(env: Env, job: GenerationJob) -> ExecutionRequest:
    """The exact build input the claim handed the worker for this job."""
    return intake._source_adaptation_request(env.session, job, env.storage)


def _download(env: Env, job: GenerationJob, token: str) -> bytes:
    response = env.client.get(
        f"/internal/generation-worker/jobs/{job.id}/source", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    return response.content


# --- WS3: secret denylist ----------------------------------------------------------------------


def test_the_denylist_covers_every_credential_shaped_api_setting():
    """Derived from app.config: a NEW secret setting cannot be forgotten."""
    secretish = [
        name
        for name in Settings.model_fields
        if any(part in name for part in ("key", "secret", "token", "password", "database_url", "webhook", "account"))
    ]
    assert len(secretish) >= 20
    for name in secretish:
        assert preflight.forbidden_environment({name.upper(): "x"}) == [name.upper()], name


@pytest.mark.parametrize(
    "name",
    [
        "DATABASE_URL",
        "DATABASE_PRIVATE_URL",
        "PGPASSWORD",
        "R2_PRIVATE_SECRET_ACCESS_KEY",
        "R2_ACCESS_KEY_ID",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "RESEND_API_KEY",
        "N8N_API_KEY",
        "N8N_BASE_URL",
        "INTERNAL_AUTOMATION_TOKEN",
        "CREDENTIAL_ENCRYPTION_KEY",
        "GENERATION_WORKER_SIGNING_KEY",
        "GENERATION_WORKER_TOKEN_SHA256",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "HIGGSFIELD_API_KEY_SECRET",
        "GOOGLE_REVIEWS_API_KEY",
        "SMTP_PASSWORD",
        "RAILWAY_TOKEN",
        "NPM_TOKEN",
        "SOME_VENDOR_SECRET",
    ],
)
def test_a_forbidden_credential_refuses_startup_and_is_never_printed(tmp_path, name):
    value = "super-secret-" + uuid.uuid4().hex
    report = _preflight(tmp_path, _base_environ(**{name: value}))
    assert not report.ok and "no_platform_credentials" in _failed(report)
    assert name in report.to_json() and value not in report.to_json()


def test_a_url_with_an_embedded_password_is_forbidden_whatever_its_name(tmp_path):
    report = _preflight(tmp_path, _base_environ(SOMETHING="postgresql://u:hunter2@db.internal:5432/x"))
    assert "no_platform_credentials" in _failed(report) and "hunter2" not in report.to_json()


def test_the_worker_token_and_ordinary_platform_variables_are_allowed(tmp_path):
    report = _preflight(tmp_path, _base_environ())
    assert report.ok, report.failures
    assert GOOD_TOKEN not in report.to_json()


# --- WS2: startup preflight -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"GWA_WORKER_TOKEN": ""}, "worker_token"),
        ({"GWA_WORKER_TOKEN": "short"}, "worker_token"),
        ({"GWA_API_BASE_URL": ""}, "api_url"),
        ({"GWA_API_BASE_URL": "http://api.example.com"}, "api_url"),
        ({"GWA_API_BASE_URL": "https://user:pw@api.example.com"}, "api_url"),
        ({"GWA_API_BASE_URL": "https://api.example.com/?x=1"}, "api_url"),
        ({"GWA_WORKER_CONCURRENCY": "2"}, "concurrency"),
    ],
)
def test_misconfiguration_fails_preflight_with_a_clear_reason(tmp_path, change, check):
    report = _preflight(tmp_path, _base_environ(**change))
    assert check in _failed(report)


def test_missing_bun_or_node_fails_preflight(tmp_path):
    no_bun = _preflight(tmp_path, _base_environ(), which=lambda name: None if name == "bun" else "/usr/bin/" + name)
    assert "bun" in _failed(no_bun)
    no_node = _preflight(tmp_path, _base_environ(), which=lambda name: None)
    assert {"bun", "node"} <= _failed(no_node)


def test_missing_chromium_fails_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "_chromium_launches", lambda: "cannot launch: Error: executable doesn't exist")
    report = preflight.run_preflight(environ=_base_environ(), isolation="supervised-process", work_root=tmp_path / "w")
    assert "chromium" in _failed(report)


def test_real_chromium_launches_in_preflight(tmp_path):
    report = preflight.run_preflight(environ=_base_environ(), isolation="supervised-process", work_root=tmp_path / "w")
    chromium = next(c for c in report.checks if c.name == "chromium")
    assert chromium.ok, chromium.detail


def test_an_unwritable_workspace_fails_preflight(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    report = preflight.run_preflight(
        environ=_base_environ(), isolation="supervised-process", work_root=blocker / "work", launch_chromium=False
    )
    assert "workspace" in _failed(report)


def test_serve_refuses_before_any_network_call_when_a_secret_is_inherited(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env
    for name, value in _base_environ(DATABASE_URL="postgresql://u:p@db/x").items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GWA_WORKER_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setattr(preflight, "_chromium_launches", lambda: "ok test")
    monkeypatch.setattr(worker_main.httpx, "Client", lambda *a, **k: pytest.fail("must not contact the API"))
    assert worker_main.serve(once=True, state=worker_main.WorkerState()) == worker_main.EX_CONFIG


def test_a_secret_appearing_later_stops_the_worker_before_its_next_claim(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    client = httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("must not claim")), base_url="https://a")
    with pytest.raises(worker_main.WorkerConfigError, match="DATABASE_URL"):
        worker_main.run_once(client, worker_id="w", prepared_dependencies=None, isolation="supervised-process")


def test_the_token_and_api_url_are_removed_from_the_worker_environment(monkeypatch):
    monkeypatch.setenv("GWA_WORKER_TOKEN", GOOD_TOKEN)
    monkeypatch.setenv("GWA_API_BASE_URL", "https://api.example.com")
    worker_main.scrub_control_plane_environment()
    assert "GWA_WORKER_TOKEN" not in os.environ and "GWA_API_BASE_URL" not in os.environ


# --- WS4: child-process environment -----------------------------------------------------------


def test_a_supervised_step_sees_only_its_allowlist_and_a_private_home(tmp_path, monkeypatch):
    monkeypatch.setenv("GWA_WORKER_TOKEN", MARKER)
    monkeypatch.setenv("DATABASE_URL", MARKER)
    workspace = tmp_path / "job" / "app"
    workspace.mkdir(parents=True)
    runner = SupervisedProcessRunner()
    runner.run(
        ["/bin/sh", "-c", 'env > env.txt; touch "$HOME/home-file"'],
        workspace=workspace,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp", "TMPDIR": "/tmp"},
        limits=SandboxLimits(wall_timeout_seconds=30),
        step="probe",
    )
    text = (workspace / "env.txt").read_text()
    seen = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert MARKER not in text
    assert set(seen) - {"PWD", "SHLVL", "_", "OLDPWD"} == {"PATH", "LANG", "HOME", "TMPDIR"}
    assert seen["HOME"].startswith(str(tmp_path / "job")) and seen["HOME"] != "/tmp"
    assert not Path(seen["HOME"]).exists()  # the step's home is removed with the step
    assert runner.step_peak_rss_kb["probe"] > 0


@pytest.mark.parametrize("name", ["GWA_WORKER_TOKEN", "DATABASE_URL", "CLOUDFLARE_API_TOKEN", "GWA_API_BASE_URL"])
def test_a_supervised_step_refuses_an_environment_carrying_platform_variables(tmp_path, name):
    with pytest.raises(SandboxError, match=name):
        SupervisedProcessRunner().run(
            ["/bin/true"],
            workspace=tmp_path,
            env={"PATH": "/usr/bin:/bin", name: "x"},
            limits=SandboxLimits(),
            step="probe",
        )


def test_the_dependency_install_environment_is_built_from_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("GWA_WORKER_TOKEN", MARKER)
    tools = static_build.Toolchain(bun=Path("/opt/bun/bin/bun"), node_bin=Path("/usr/bin"))
    install_env = static_build._install_env(tools, tmp_path)
    assert set(install_env) == {"PATH", "HOME", "TMPDIR", "BUN_INSTALL_CACHE_DIR", "NO_COLOR", "DO_NOT_TRACK", "LANG"}
    assert MARKER not in json.dumps(install_env) and not preflight.forbidden_environment(install_env)


def _processes_with_home(home: str) -> list[dict[str, str]]:
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            raw = (proc / "environ").read_bytes()
        except OSError:
            continue
        environ = dict(item.split("=", 1) for item in raw.decode(errors="replace").split("\0") if "=" in item)
        if environ.get("HOME") == home:
            found.append(environ)
    return found


def test_chromium_gets_only_the_explicit_browser_environment(tmp_path, monkeypatch):
    """Even if the token were still in the worker's environment, the real
    Chromium processes Visual QA launches never see it."""
    from playwright.sync_api import sync_playwright

    monkeypatch.setenv("GWA_WORKER_TOKEN", MARKER)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", MARKER)
    home = tmp_path / "qa-home"
    home.mkdir()
    browser_env: dict[str, str | float | bool] = dict(preflight.browser_env(home))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"], env=browser_env)
        try:
            chromium = _processes_with_home(str(home))
        finally:
            browser.close()
    assert chromium, "the Chromium processes were not found"
    for environ in chromium:
        assert MARKER not in json.dumps(environ)
        assert not preflight.forbidden_environment(environ)
        assert not any(name.startswith("GWA_") for name in environ)


def test_a_real_vite_build_cannot_see_the_worker_token_or_platform_secrets(env: Env, tmp_path, monkeypatch):
    """The export's own build code (vite.config.ts runs in Node during
    `bun run build`) dumps the environment it was given: neither the worker
    token nor a platform secret is in it, although both are set in the
    worker's own environment for this test. (It CAN write outside its
    workspace — supervised-process mode has no filesystem isolation.)"""
    if not static_build.shutil.which("bun"):
        pytest.skip("bun is required")
    monkeypatch.setenv("GWA_WORKER_TOKEN", MARKER)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:" + MARKER + "@db/x")
    monkeypatch.setenv("R2_PRIVATE_SECRET_ACCESS_KEY", MARKER)
    dump = tmp_path / "build-env.json"
    config = (FIXTURE / "vite.config.ts").read_text(encoding="utf-8")
    probe = (
        '\nimport { writeFileSync } from "node:fs";\n'
        f"writeFileSync({json.dumps(str(dump))}, JSON.stringify(process.env));\n"
    )
    _, job, token = _import_and_build(env, _variant_zip(tmp_path, "probe", {"vite.config.ts": config + probe}))
    result = execute_source_adaptation(
        _claimed_request(env, job), _download(env, job, token), runner=SupervisedProcessRunner()
    )
    assert result.status == "succeeded", result.error
    seen = json.loads(dump.read_text())
    assert MARKER not in json.dumps(seen)
    assert not preflight.forbidden_environment(seen)
    assert not any(name.startswith("GWA_") for name in seen)
    assert result.metadata["build_peak_rss_kb"] > 0 and result.metadata["artifact_files"] > 0


# --- WS7: workspace lifecycle -------------------------------------------------------------------


def _alive(tag: str) -> bool:
    return subprocess.run(["pgrep", "-f", tag], capture_output=True).returncode == 0  # noqa: S603, S607


def test_a_timed_out_step_kills_its_whole_process_tree_and_removes_its_home(tmp_path):
    workspace = tmp_path / "job" / "app"
    workspace.mkdir(parents=True)
    tag = "gwa-r51-sleeper-" + uuid.uuid4().hex[:8]
    with pytest.raises(SandboxError, match="timed out"):
        SupervisedProcessRunner().run(
            ["/bin/bash", "-c", f"(exec -a {tag} sleep 60) & (exec -a {tag} sleep 60)"],
            workspace=workspace,
            env={"PATH": "/usr/bin:/bin"},
            limits=SandboxLimits(wall_timeout_seconds=1),
            step="sleeper",
        )
    time.sleep(0.3)
    assert not _alive(tag)
    assert list((tmp_path / "job").iterdir()) == [workspace]  # no step home left behind


def test_a_job_that_hits_its_deadline_fails_as_a_resource_limit_and_leaves_nothing(env: Env, tmp_path, monkeypatch):
    if not static_build.shutil.which("bun"):
        pytest.skip("bun is required")
    _, job, token = _import_and_build(env, _variant_zip(tmp_path, "deadline"))
    source = _download(env, job, token)
    job_dir = tmp_path / "job-root"
    job_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(job_dir))
    result = execute_source_adaptation(
        _claimed_request(env, job), source, runner=SupervisedProcessRunner(), deadline_seconds=0.5
    )
    assert result.status == "failed" and result.failure_kind is GenerationFailureKind.RESOURCE_LIMIT, result.error
    assert list(job_dir.iterdir()) == []


class _FakeWorkerAPI:
    """The control plane as the worker sees it: claim, source, result."""

    def __init__(self, request: ExecutionRequest | None, *, jobs_to_hand_out: int = 1) -> None:
        self.request = request
        self.remaining = jobs_to_hand_out
        self.claims = 0
        self.results: list[dict] = []

    def handler(self, http: httpx.Request) -> httpx.Response:
        if http.url.path.endswith("/claim"):
            self.claims += 1
            if self.request is None or self.remaining == 0:
                return httpx.Response(204)
            self.remaining -= 1
            return httpx.Response(200, json={"request": self.request.model_dump(mode="json"), "job_token": "jt"})
        if http.url.path.endswith("/source"):
            return httpx.Response(200, content=b"zip")
        self.results.append(json.loads(http.content))
        return httpx.Response(204)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="https://api.example.com")


def _source_request() -> ExecutionRequest:
    return ExecutionRequest.model_validate(
        {
            "job_id": str(uuid.uuid4()),
            "attempt": 1,
            "business_id": str(uuid.uuid4()),
            "api_base_url": "https://api.example.com",
            "source_family": "higgsfield-tanstack",
            "source_sha256": "0" * 64,
            "job_kind": "source_adaptation",
            "trust_class": "supervised_source",
            "adaptation_plan": {},
            "plan_sha256": "1" * 64,
            "site_origin": "https://site.example",
        }
    )


def _isolated_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(worker_main.worker_preflight, "forbidden_environment", lambda environ=None: [])
    monkeypatch.setenv("GWA_WORKER_WORK_ROOT", str(tmp_path / "work"))


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "raises"])
def test_every_job_workspace_is_removed_whatever_the_outcome(tmp_path, monkeypatch, outcome):
    _isolated_worker(monkeypatch, tmp_path)
    monkeypatch.setenv("TMPDIR", "/tmp")
    request = _source_request()
    seen: dict[str, str] = {}

    def fake_execute(req, source, *, runner):
        seen["tmp"] = tempfile.gettempdir()
        seen["env_tmp"] = os.environ["TMPDIR"]
        (Path(tempfile.mkdtemp()) / "node_modules").mkdir()  # adapted source / deps / browser data
        if outcome == "raises":
            raise RuntimeError("unexpected")
        ok = outcome == "succeeded"
        return ExecutionResult(
            job_id=req.job_id,
            attempt=req.attempt,
            status=outcome,
            failure_kind=None if ok else GenerationFailureKind.BUILD,
            candidate_archive="eA==" if ok else None,
            candidate_sha256="0" * 64 if ok else None,
        )

    monkeypatch.setattr(worker_main, "execute_source_adaptation", fake_execute)
    api = _FakeWorkerAPI(request)
    args = {"worker_id": "w", "prepared_dependencies": None, "isolation": "supervised-process"}
    if outcome == "raises":
        with pytest.raises(RuntimeError):
            worker_main.run_once(api.client(), **args)
    else:
        worker_main.run_once(api.client(), **args)
    assert seen["tmp"].startswith(str(tmp_path / "work" / f"job-{request.job_id}-1-"))
    assert seen["env_tmp"] == seen["tmp"]
    assert list((tmp_path / "work").iterdir()) == []
    assert os.environ["TMPDIR"] == "/tmp" and tempfile.tempdir is None


def test_a_restarted_worker_starts_from_an_empty_work_root(tmp_path):
    root = tmp_path / "work"
    (root / "job-old" / "node_modules").mkdir(parents=True)
    (root / "stray.zip").write_bytes(b"x")
    worker_main.reset_work_root(root)
    assert list(root.iterdir()) == []


# --- WS10: SIGTERM, lease expiry, bounded requeue, duplicates -------------------------------------


def test_sigterm_during_a_job_releases_the_attempt_and_cleans_up(tmp_path, monkeypatch):
    _isolated_worker(monkeypatch, tmp_path)
    state = worker_main.WorkerState()
    monkeypatch.setattr(worker_main, "STATE", state)

    def interrupted(req, source, *, runner):
        assert state.phase == "executing"
        worker_main._on_signal(signal.SIGTERM, None)
        pytest.fail("the handler must interrupt the job")

    monkeypatch.setattr(worker_main, "execute_source_adaptation", interrupted)
    api = _FakeWorkerAPI(_source_request())
    worker_main.run_once(
        api.client(), worker_id="w", prepared_dependencies=None, isolation="supervised-process", state=state
    )
    assert len(api.results) == 1 and api.results[0]["failure_kind"] == "worker_lost"
    assert "SIGTERM" in api.results[0]["error"] and state.stop.is_set()
    assert list((tmp_path / "work").iterdir()) == []


def test_a_real_sigterm_kills_the_running_build_tree(tmp_path):
    """A separate Python process runs a supervised step exactly as the
    worker does; SIGTERM must leave no build process behind."""
    tag = "gwa-r51-term-" + uuid.uuid4().hex[:8]
    script = f"""
import signal, sys
from pathlib import Path
from app.worker import __main__ as m
from app.creative.frontend_engine.sandbox import SupervisedProcessRunner, SandboxLimits
signal.signal(signal.SIGTERM, m._on_signal)
m.STATE.tick("executing")
ws = Path({str(tmp_path)!r}) / "job" / "app"; ws.mkdir(parents=True)
print("ready", flush=True)
try:
    SupervisedProcessRunner().run(["/bin/bash", "-c", "(exec -a {tag} sleep 60) & (exec -a {tag} sleep 60)"],
        workspace=ws, env={{"PATH": "/usr/bin:/bin"}}, limits=SandboxLimits(wall_timeout_seconds=120), step="build")
except m.WorkerShutdown:
    print("shutdown", flush=True); sys.exit(0)
sys.exit(3)
"""
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=API_ROOT, stdout=subprocess.PIPE, text=True)  # noqa: S603
    assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
    for _ in range(50):
        if _alive(tag):
            break
        time.sleep(0.1)
    assert _alive(tag)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=20) == 0 and "shutdown" in proc.stdout.read()
    time.sleep(0.3)
    assert not _alive(tag)
    assert [p.name for p in (tmp_path / "job").iterdir()] == ["app"]


def _expire(env: Env, job: GenerationJob) -> None:
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    env.session.flush()


def _claim(env: Env):
    return env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )


def test_a_lost_source_job_is_requeued_and_the_lost_attempt_can_no_longer_act(env: Env, built):
    _, job, old_token = _import_and_build(env, built.zip_bytes)
    _expire(env, job)
    reclaimed = _claim(env)
    assert reclaimed.status_code == 200
    assert job.status is GenerationJobStatus.RUNNING and job.attempts == 2
    assert reclaimed.json()["request"]["attempt"] == 2
    # The lost attempt's token is dead for both download and result.
    stale = env.client.get(
        f"/internal/generation-worker/jobs/{job.id}/source", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert stale.status_code == 401
    late = built.result.model_copy(update={"job_id": job.id, "attempt": 1})
    response = env.client.post(
        f"/internal/generation-worker/jobs/{job.id}/result",
        headers={"Authorization": f"Bearer {old_token}", "Content-Type": "application/json"},
        content=late.model_dump_json(),
    )
    assert response.status_code == 401
    # The live attempt succeeds exactly once: one artifact, never two.
    token = reclaimed.json()["job_token"]
    assert _submit(env, job, token, built.result).status_code == 204
    assert _submit(env, job, token, built.result).status_code == 409
    assert env.session.scalar(select(func.count()).select_from(GenerativeWebsiteArtifact)) == 1
    row = env.session.scalar(select(SourceImport).where(SourceImport.job_id == job.id))
    assert row is not None and row.status is SourceImportStatus.PREVIEW_READY


def test_a_worker_released_attempt_goes_back_to_the_queue(env: Env, built):
    body, job, token = _import_and_build(env, built.zip_bytes)
    released = ExecutionResult(
        job_id=job.id, attempt=1, status="failed", failure_kind=GenerationFailureKind.WORKER_LOST, error="SIGTERM"
    )
    assert _submit(env, job, token, released).status_code == 204
    assert job.status is GenerationJobStatus.QUEUED and job.attempts == 1
    draft = env.session.get(WebsiteDraft, job.draft_id)
    assert draft is not None and draft.status is WebsiteDraftStatus.BUILDING
    assert env.client.get(env.url(f"/{body['id']}"), headers=env.headers).json()["stage"] == "queued"
    env.session.flush()  # what the request's commit does in production
    assert _claim(env).json()["request"]["attempt"] == 2


def test_requeue_is_bounded_and_the_import_never_stays_building(env: Env, built):
    body, job, _ = _import_and_build(env, built.zip_bytes)
    for _ in range(jobs.MAX_SOURCE_ATTEMPTS - 1):
        _expire(env, job)
        assert _claim(env).status_code == 200
    assert job.attempts == jobs.MAX_SOURCE_ATTEMPTS
    _expire(env, job)
    assert _claim(env).status_code == 204  # failed for good; nothing else queued
    assert job.status is GenerationJobStatus.FAILED and job.failure_kind is GenerationFailureKind.WORKER_LOST
    state = env.client.get(env.url(f"/{body['id']}"), headers=env.headers).json()
    assert state["status"] == "build_failed" and state["stage"] == "build_failed"
    assert env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers).status_code == 202  # rebuildable


def test_a_generative_job_is_still_never_retried_automatically(env: Env):
    job = jobs.submit_job(
        env.session,
        tenant_id=env.tenant.id,
        business_id=env.business.id,
        idempotency_key="gen-1",
        input_sha256="0" * 64,
        source_key="k",
        source_sha256="0" * 64,
        api_base_url=None,
    )
    job.status = GenerationJobStatus.RUNNING
    job.attempts = 1
    assert jobs.requeue_lost(job, reason="lost") is False


# --- WS9: the worker credential's authority ------------------------------------------------------


def test_the_worker_token_cannot_act_as_an_operator(env: Env, built):
    body, job, _ = _import_and_build(env, built.zip_bytes)
    # The REAL session authentication and tenant authorization.
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_tenant_id, None)
    client = TestClient(app)
    tenant = {"X-Tenant-Id": str(env.tenant.id)}
    business = f"/businesses/{env.business.id}"
    attempts = [
        ("get", f"{business}/source-imports"),
        ("get", f"{business}/source-imports/{body['id']}"),
        ("get", f"{business}/source-imports/{body['id']}/diagnostics"),
        ("post", f"{business}/source-imports/{body['id']}/build"),
        ("post", f"{business}/website-drafts/{job.draft_id}/approve"),
        ("post", f"{business}/website-drafts/{job.draft_id}/publish"),
        ("post", f"{business}/website-drafts/{job.draft_id}/preview"),
        ("get", f"{business}/leads"),
        ("get", "/businesses"),
    ]
    for method, url in attempts:
        bearer = getattr(client, method)(url, headers={**env.worker(), **tenant})
        assert bearer.status_code == 401, (url, bearer.status_code)
        client.cookies.set(settings.session_cookie_name, WORKER_TOKEN)
        cookie = getattr(client, method)(url, headers=tenant)
        client.cookies.clear()
        assert cookie.status_code == 401, (url, cookie.status_code)


def test_the_worker_token_reaches_no_source_and_job_tokens_are_job_bound(env: Env, built, tmp_path):
    _, job_a, token_a = _import_and_build(env, built.zip_bytes)
    source_a = f"/internal/generation-worker/jobs/{job_a.id}/source"
    assert env.client.get(source_a, headers=env.worker()).status_code == 401  # claim-only credential
    as_job = {"Authorization": f"Bearer {token_a}"}
    assert env.client.post("/internal/generation-worker/claim", headers=as_job).status_code == 401
    _, job_b, _ = _import_and_build(env, _variant_zip(tmp_path, "b", {"README.md": "b"}))
    assert env.client.get(f"/internal/generation-worker/jobs/{job_b.id}/source", headers=as_job).status_code == 401
    assert _submit(env, job_a, token_a, built.result).status_code == 204
    assert env.client.get(source_a, headers=as_job).status_code == 409  # finished: nothing to download


def test_the_worker_protocol_exposes_no_publish_or_approve_surface():
    from app.routers.generation_worker import router

    assert sorted((sorted(route.methods), route.path) for route in router.routes) == [  # type: ignore[attr-defined]
        (["GET"], "/internal/generation-worker/jobs/{job_id}/source"),
        (["POST"], "/internal/generation-worker/claim"),
        (["POST"], "/internal/generation-worker/jobs/{job_id}/result"),
    ]


# --- WS11: concurrency ------------------------------------------------------------------------------


def test_the_service_loop_never_runs_more_than_one_job_at_a_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _isolated_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(worker_main, "selftest", lambda: 0)
    monkeypatch.setattr(worker_main, "startup_preflight", lambda isolation: True)
    monkeypatch.setenv("GWA_WORKER_ISOLATION", "supervised-process")
    monkeypatch.setenv("GWA_WORKER_TOKEN", GOOD_TOKEN)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("GWA_WORKER_HEALTH_PORT", raising=False)
    state = worker_main.WorkerState()
    api = _FakeWorkerAPI(_source_request(), jobs_to_hand_out=3)
    tally = {"now": 0, "max": 0, "claims_seen": []}

    def fake_execute(req, source, *, runner):
        tally["now"] += 1
        tally["max"] = max(tally["max"], tally["now"])
        tally["claims_seen"].append(api.claims)
        time.sleep(0.05)
        tally["now"] -= 1
        if len(tally["claims_seen"]) == 3:
            state.stop.set()
        return ExecutionResult(
            job_id=req.job_id, attempt=req.attempt, status="failed", failure_kind=GenerationFailureKind.BUILD
        )

    monkeypatch.setattr(worker_main, "execute_source_adaptation", fake_execute)
    monkeypatch.setattr(worker_main, "_client", lambda token: api.client())
    assert worker_main.serve(once=False, state=state) == 0
    assert tally["max"] == 1
    assert tally["claims_seen"] == [1, 2, 3]  # each job finished before the next claim


# --- WS12: health ---------------------------------------------------------------------------------


def _get(port: int, path: str) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body) if body.startswith(b"{") else None


def test_health_is_ready_only_after_preflight_and_while_the_loop_is_alive():
    state = worker_main.WorkerState()
    server = worker_main.start_health_server(0, state)
    port = server.server_address[1]
    try:
        assert _get(port, "/health") == (503, {"ready": False, "phase": "starting", "preflight": False})
        state.preflight_ok = True
        state.tick("idle")
        assert _get(port, "/health")[0] == 200
        state.tick("executing")
        assert _get(port, "/health")[0] == 200
        state.job_started = time.monotonic() - (worker_main.JOB_DEADLINE_SECONDS + 600)
        assert _get(port, "/health")[0] == 503  # a job stuck far past its deadline
        state.tick("idle")
        state.last_tick = time.monotonic() - 3600
        assert _get(port, "/health")[0] == 503  # the loop stopped ticking
        assert _get(port, "/anything")[0] == 404
    finally:
        server.shutdown()


# --- WS6: dependency install --------------------------------------------------------------------------


def _lock(app_dir: Path, packages: dict[str, str], deps: dict[str, str]) -> None:
    lines = ",\n".join(
        f'    "{name}": ["{name}@{version}", "", {{}}, "sha512-{name.strip("@").replace("/", "")}{version}=="]'
        for name, version in packages.items()
    )
    (app_dir / "bun.lock").write_text('{\n  "lockfileVersion": 1,\n  "packages": {\n' + lines + "\n  }\n}\n")
    (app_dir / "package.json").write_text(json.dumps({"name": "x", "dependencies": deps}))


def test_install_may_prune_but_never_add_or_re_resolve_beyond_the_reviewed_lock(tmp_path):
    _lock(tmp_path, {"a": "1.0.0", "b": "2.0.0"}, {"a": "^1.0.0"})
    before = static_build.lock_entries(tmp_path)
    assert before is not None and len(before) == 2
    _lock(tmp_path, {"a": "1.0.0"}, {"a": "^1.0.0"})  # pruned b
    static_build.check_lock_only_pruned(before, tmp_path)
    hoisted = (tmp_path / "bun.lock").read_text().replace('"a": ["a@1.0.0"', '"c/a": ["a@1.0.0"')
    (tmp_path / "bun.lock").write_text(hoisted)  # re-hoisted: the same pinned version under another key
    static_build.check_lock_only_pruned(before, tmp_path)
    _lock(tmp_path, {"a": "1.0.1"}, {"a": "^1.0.0"})  # re-resolved
    with pytest.raises(static_build.StaticBuildError, match="re-resolved"):
        static_build.check_lock_only_pruned(before, tmp_path)
    _lock(tmp_path, {"a": "1.0.0", "evil": "6.6.6"}, {"a": "^1.0.0"})  # a package nobody declared
    with pytest.raises(static_build.StaticBuildError):
        static_build.check_lock_only_pruned(before, tmp_path)
    _lock(tmp_path, {"a": "1.0.0", "@fontsource/inter": "5.3.0"}, {"a": "^1.0.0", "@fontsource/inter": "5.3.0"})
    static_build.check_lock_only_pruned(before, tmp_path)  # the plan's own exact pin
    _lock(tmp_path, {"a": "1.0.0", "@fontsource/inter": "5.3.0"}, {"a": "^1.0.0", "@fontsource/inter": "^5.3.0"})
    with pytest.raises(static_build.StaticBuildError):
        static_build.check_lock_only_pruned(before, tmp_path)  # a range is not a reviewed pin


def test_install_runs_with_lifecycle_scripts_disabled(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    _lock(app_dir, {"a": "1.0.0"}, {"a": "1.0.0"})
    monkeypatch.setattr(static_build.subprocess, "run", fake_run)
    tools = static_build.Toolchain(bun=Path("/opt/bun/bin/bun"), node_bin=Path("/usr/bin"))
    static_build.prepare_dependencies(app_dir, tools, frozen=False)
    assert calls == [["/opt/bun/bin/bun", "install", "--ignore-scripts"]]


def test_the_worker_entrypoint_loads_no_database_storage_or_publisher_code():
    """The worker process never loads the API's session/dependency wiring,
    HTTP routers or the Cloudflare publisher. (Storage *classes* are imported
    transitively as plain code; the worker has no credential to use them.)"""
    code = (
        "import sys, app.worker.__main__\n"
        "bad=[n for n in sys.modules if n.startswith(('app.dependencies','app.publishing.cloudflare',"
        "'app.db.session','app.routers','app.main'))]\n"
        "print(','.join(sorted(bad)))\n"
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")},
        check=True,
    )
    assert out.stdout.strip() == ""


# --- WS16: upload limit before the body is read --------------------------------------------------


def _asgi_call(path: str, length: int | None) -> tuple[int | None, bool]:
    import asyncio

    from app.routers.source_imports import SourceUploadLimitMiddleware

    reached: list[bool] = []
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        reached.append(True)

    async def receive():
        raise AssertionError("the body must not be read")

    async def send(message):
        sent.append(message)

    headers = [(b"content-length", str(length).encode())] if length is not None else []
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    asyncio.run(SourceUploadLimitMiddleware(downstream)(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, bool(reached)


def test_an_oversized_upload_is_refused_from_its_content_length_unread():
    over = settings.supervised_source_max_bytes + 2 * 1024 * 1024
    assert _asgi_call(f"/businesses/{uuid.uuid4()}/source-imports", over) == (413, False)
    assert _asgi_call(f"/businesses/{uuid.uuid4()}/source-imports", settings.supervised_source_max_bytes) == (
        None,
        True,
    )
    assert _asgi_call(f"/businesses/{uuid.uuid4()}/source-imports", None) == (None, True)  # route's check applies
    assert _asgi_call(f"/businesses/{uuid.uuid4()}/assets", over) == (None, True)  # other routes untouched
