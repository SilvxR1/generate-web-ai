"""v0.2 R4.1/R4.2 — the isolated execution host's process.

    python -m app.worker --selftest   # readiness: can THIS host enforce R4?
    python -m app.worker --preflight  # R5.1: full startup checks (JSON), exit 0 = ready
    python -m app.worker --once       # claim, execute and report one job
    python -m app.worker              # service loop (one job at a time)

Configuration (the host's ONLY configuration — no platform secret):
    GWA_API_BASE_URL        e.g. https://api.example.com
    GWA_WORKER_ID           a non-secret name for logs (default: hostname)
    GWA_WORKER_ISOLATION    bubblewrap (default: the R4 sandbox, any job) or
                            supervised-process (R5: NO sandbox — separate
                            process only; the control plane then hands it
                            ONLY operator-imported, owner-reviewed sources)
    GWA_DEPENDENCY_ROOT     where trusted, read-only dependencies are prepared
    GWA_WORKER_WORK_ROOT    R5.1: parent of every per-job workspace
                            (default /tmp/gwa-worker; emptied at start)
    GWA_WORKER_CONCURRENCY  R5.1: must be 1 (the only supported value)
    GWA_WORKER_HEALTH_PORT  R5.1: serve GET /health here (default: $PORT
                            when set — Railway's healthcheck; else none)
    worker token            $CREDENTIALS_DIRECTORY/worker-token (systemd
                            LoadCredential=), else GWA_WORKER_TOKEN

R5.1.2 startup: before anything else the worker makes itself non-dumpable
(app.worker.process_protection) and refuses to start if it cannot.

R5.1 startup: `serve` runs the full preflight (app.worker.preflight) and
refuses to start (EX_CONFIG) on any failure — a forbidden platform
credential in the environment, a missing/short token, a bad API URL, a
missing toolchain, Chromium that cannot launch, an unwritable workspace.
It then REMOVES the token and API URL from its own environment, so no
child process (bun, Vite, the Playwright driver, Chromium) can inherit them.

Concurrency is exactly one job per process, by construction: the loop
claims, executes and reports one job before it claims the next, so a second
queued job stays QUEUED. Horizontal scaling later = more worker processes or
hosts pulling from the same queue (claims are atomic server-side).

Shutdown (SIGTERM, e.g. a Railway redeploy): an idle worker exits at once;
a building worker kills the build's process tree, removes the job
workspace, reports its attempt as WORKER_LOST (the control plane requeues a
source job) and exits. A worker killed outright is recovered by the lease.

Logs carry worker id, job id, attempt, durations and safe failure
categories only — never a token, the source, BusinessTruth, customer
content or the environment.
"""

import argparse
import json
import logging
import os
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from app.creative.frontend_engine.dependencies import DependencyPreparationError, prepare_dependencies
from app.creative.frontend_engine.sandbox import SandboxError, SupervisedProcessRunner, detect_runner
from app.domain.enums import GenerationFailureKind, GenerationJobKind
from app.worker import preflight as worker_preflight
from app.worker import process_protection
from app.worker.executor import execute
from app.worker.protocol import MAX_EXPORT_SNAPSHOT_BYTES, ExecutionRequest, ExecutionResult
from app.worker.source_executor import JOB_DEADLINE_SECONDS, execute_source_adaptation

logger = logging.getLogger("app.worker")
REQUIRED_LIMITS = ("wall_timeout", "cpu", "file_size", "tmp_size", "memory", "process_count")
IDLE_SECONDS = 10
MAX_BACKOFF_SECONDS = 300
RESULT_ATTEMPTS = 5
DEFAULT_DEPENDENCY_ROOT = "/var/lib/gwa-worker/deps"
DEFAULT_WORK_ROOT = "/tmp/gwa-worker"
# Permanent problems (host cannot isolate, credential missing/revoked, bad
# configuration): systemd must NOT restart-loop on these
# (RestartPreventExitStatus=78 in deploy/worker/gwa-worker.service).
EX_CONFIG = 78


class WorkerConfigError(Exception):
    """The worker is not configured to talk to the control plane."""


class WorkerShutdown(BaseException):  # noqa: N818 — like KeyboardInterrupt: not an error to catch broadly
    """SIGTERM/SIGINT arrived while a job was executing."""


class WorkerState:
    """What the health endpoint reports (never a token, URL or job input)."""

    def __init__(self) -> None:
        self.preflight_ok = False
        self.phase = "starting"  # starting | idle | executing | reporting | stopping
        self.last_tick = time.monotonic()
        self.job_started: float | None = None
        self.stop = threading.Event()

    def tick(self, phase: str) -> None:
        self.phase = phase
        self.last_tick = time.monotonic()
        self.job_started = time.monotonic() if phase == "executing" else None

    def healthy(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self.preflight_ok or self.phase in ("starting", "stopping"):
            return False
        if self.phase == "executing" and self.job_started is not None:
            return now - self.job_started < JOB_DEADLINE_SECONDS + 120
        return now - self.last_tick < MAX_BACKOFF_SECONDS + 120


STATE = WorkerState()


def _on_signal(signum: int, frame: object) -> None:
    STATE.stop.set()
    if STATE.phase == "executing":
        STATE.phase = "stopping"
        raise WorkerShutdown(signal.Signals(signum).name)


def start_health_server(port: int, state: WorkerState = STATE) -> ThreadingHTTPServer:
    """GET /health -> 200 only after preflight passed and while the loop is
    alive; 503 otherwise. Nothing else is served; no request is logged."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server API
            if self.path.split("?", 1)[0] != "/health":
                self.send_response(404)
                self.end_headers()
                return
            ok = state.healthy()
            body = json.dumps({"ready": ok, "phase": state.phase, "preflight": state.preflight_ok}).encode()
            self.send_response(200 if ok else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 — a container's own health port
    threading.Thread(target=server.serve_forever, name="gwa-worker-health", daemon=True).start()
    return server


def health_port() -> int | None:
    raw = os.environ.get("GWA_WORKER_HEALTH_PORT") or os.environ.get("PORT")
    return int(raw) if raw and raw.isdigit() else None


def work_root() -> Path:
    return Path(os.environ.get("GWA_WORKER_WORK_ROOT", DEFAULT_WORK_ROOT))


ISOLATION_MODES = ("bubblewrap", "supervised-process")


def isolation_mode() -> str:
    mode = os.environ.get("GWA_WORKER_ISOLATION", "bubblewrap").strip() or "bubblewrap"
    if mode not in ISOLATION_MODES:
        raise WorkerConfigError(f"GWA_WORKER_ISOLATION must be one of {ISOLATION_MODES}")
    return mode


def selftest() -> int:
    """Ready only if the sandbox can be created AND every required limit
    is enforced on this host (a host without a cgroup scope is not ready).
    R5 supervised-process mode: ready if the toolchain exists — and it says
    plainly which isolation it does NOT provide."""
    try:
        mode = isolation_mode()
    except WorkerConfigError as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}))
        return 1
    if mode == "supervised-process":
        supervised = SupervisedProcessRunner()
        tools = {name: shutil.which(name) is not None for name in ("bun", "node")}
        ready = all(tools.values())
        print(
            json.dumps(
                {
                    "ready": ready,
                    "runner": supervised.name,
                    "accepts": "supervised sources only",
                    "limits_enforced": supervised.limits_enforced(),
                    "toolchain": tools,
                }
            )
        )
        return 0 if ready else 1
    try:
        runner = detect_runner()
    except SandboxError as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}))
        return 1
    enforced = runner.limits_enforced()
    missing = [name for name in REQUIRED_LIMITS if not enforced.get(name)]
    print(json.dumps({"ready": not missing, "runner": runner.name, "limits_enforced": enforced, "missing": missing}))
    return 0 if not missing else 1


def load_worker_token() -> str:
    token = worker_preflight.read_worker_token()
    if not token:
        raise WorkerConfigError("no worker token (LoadCredential=worker-token or GWA_WORKER_TOKEN)")
    return token


def scrub_control_plane_environment() -> None:
    """After the token and URL are read: nothing this process starts later
    (bun, Vite, the Playwright driver, Chromium) can inherit them."""
    for name in (worker_preflight.WORKER_TOKEN_ENV, worker_preflight.API_URL_ENV, "CREDENTIALS_DIRECTORY"):
        os.environ.pop(name, None)


def startup_preflight(isolation: str) -> bool:
    report = worker_preflight.run_preflight(isolation=isolation, work_root=work_root())
    if report.ok:
        logger.info("preflight passed %s", report.to_json())
    else:
        logger.error("preflight failed — refusing to start: %s", "; ".join(report.failures))
    return report.ok


def reset_work_root(root: Path) -> None:
    """A previous process may have died mid-job: start from an empty root."""
    if root.exists():
        for child in root.iterdir():
            shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)
    root.mkdir(parents=True, exist_ok=True)


def _submit_result(
    client: httpx.Client,
    *,
    request: ExecutionRequest,
    job_token: str,
    result: ExecutionResult,
    attempts: int = RESULT_ATTEMPTS,
) -> str:
    """Retries transient failures only. The control plane accepts a result
    exactly once per job/attempt; a 409 after an earlier attempt that may
    have landed means it already did — never a second READY."""
    url = f"/internal/generation-worker/jobs/{request.job_id}/result"
    body = result.model_dump_json()
    for attempt in range(1, attempts + 1):
        try:
            response = client.post(
                url,
                content=body,
                headers={"Authorization": f"Bearer {job_token}", "Content-Type": "application/json"},
            )
        except httpx.TransportError:
            outcome = "transport_error"
        else:
            if response.status_code == 204:
                return "accepted"
            if response.status_code == 409:
                return "already_final" if attempt > 1 else "rejected_conflict"
            if response.status_code in (401, 404, 422):
                return f"rejected_{response.status_code}"  # not retryable: token expired/revoked or bad payload
            outcome = f"http_{response.status_code}"
        logger.warning("result submission failed job_id=%s try=%d outcome=%s", request.job_id, attempt, outcome)
        if attempt < attempts:
            time.sleep(min(2**attempt, 60))
    return "gave_up"  # the job's lease expires and it fails as worker_lost — never READY


def _download_source(client: httpx.Client, request: ExecutionRequest, job_token: str) -> bytes:
    response = client.get(
        f"/internal/generation-worker/jobs/{request.job_id}/source",
        headers={"Authorization": f"Bearer {job_token}"},
    )
    response.raise_for_status()
    if len(response.content) > MAX_EXPORT_SNAPSHOT_BYTES:
        raise ValueError("source snapshot exceeds its size limit")
    return response.content


def run_once(
    client: httpx.Client,
    *,
    worker_id: str,
    prepared_dependencies: Path | None,
    isolation: str = "bubblewrap",
    state: WorkerState = STATE,
) -> bool:
    """Claims and processes at most one job. Returns False when idle."""
    if not process_protection.is_non_dumpable():  # R5.1.2: re-checked before EVERY claim
        raise WorkerConfigError("the worker process is dumpable: same-UID builds could read its credentials")
    forbidden = worker_preflight.forbidden_environment()
    if forbidden:  # re-checked before EVERY claim, not only at start
        raise WorkerConfigError(f"forbidden platform credentials in the environment: {', '.join(forbidden)}")
    response = client.post("/internal/generation-worker/claim", json={"isolation": isolation})
    if response.status_code == 204:
        return False
    if response.status_code == 401:
        raise WorkerConfigError("worker credential rejected (revoked or rotated)")
    response.raise_for_status()
    body = response.json()
    request = ExecutionRequest.model_validate(body["request"])
    started = time.monotonic()
    logger.info(
        "job started worker=%s job_id=%s attempt=%d kind=%s",
        worker_id,
        request.job_id,
        request.attempt,
        request.job_kind.value,
    )
    job_dir = work_root() / f"job-{request.job_id}-{request.attempt}-{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True)
    previous_tmp = os.environ.get("TMPDIR")
    # Every temporary file of this job (workspace, step homes, the browser
    # profile of the Playwright driver) lands under job_dir.
    tempfile.tempdir = str(job_dir)
    os.environ["TMPDIR"] = str(job_dir)
    interrupted = False
    try:
        state.tick("executing")
        if state.stop.is_set():
            raise WorkerShutdown("stop requested before the job started")
        if request.job_kind is GenerationJobKind.SOURCE_ADAPTATION:
            runner = SupervisedProcessRunner() if isolation == "supervised-process" else detect_runner()
            source = _download_source(client, request, body["job_token"])
            result = execute_source_adaptation(request, source, runner=runner)
        elif isolation != "bubblewrap":
            result = ExecutionResult(
                job_id=request.job_id,
                attempt=request.attempt,
                status="failed",
                failure_kind=GenerationFailureKind.SANDBOX_UNAVAILABLE,
                error="generated code only ever runs in the bubblewrap sandbox",
            )
        else:
            result = execute(request, prepared_dependencies=prepared_dependencies)
    except WorkerShutdown as exc:
        interrupted = True
        result = ExecutionResult(
            job_id=request.job_id,
            attempt=request.attempt,
            status="failed",
            failure_kind=GenerationFailureKind.WORKER_LOST,
            error=f"worker stopped during the job ({exc})",
        )
    finally:
        tempfile.tempdir = None
        if previous_tmp is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous_tmp
        shutil.rmtree(job_dir, ignore_errors=True)
    state.tick("reporting")
    outcome = _submit_result(
        client,
        request=request,
        job_token=body["job_token"],
        result=result,
        attempts=1 if interrupted else RESULT_ATTEMPTS,
    )
    logger.info(
        "job finished worker=%s job_id=%s attempt=%d status=%s failure=%s duration_ms=%d report=%s",
        worker_id,
        request.job_id,
        request.attempt,
        result.status,
        result.failure_kind.value if result.failure_kind else "-",
        int((time.monotonic() - started) * 1000),
        outcome,
    )
    return True


def _client(token: str, base: str | None = None) -> httpx.Client:
    try:
        base = worker_preflight.validate_api_url(os.environ.get("GWA_API_BASE_URL") if base is None else base)
    except ValueError as exc:
        raise WorkerConfigError(str(exc)) from exc
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(60.0, read=300.0),
    )


def serve(*, once: bool, state: WorkerState = STATE) -> int:
    # R5.1.2: FIRST, before any child process exists (selftest already spawns
    # some): same-UID processes must not read this process's startup
    # environment or memory through procfs. No protection, no worker.
    try:
        process_protection.make_non_dumpable()
    except process_protection.ProcessProtectionError as exc:
        logger.error("worker not started: process protection unavailable (%s)", exc)
        return EX_CONFIG
    if selftest() != 0:
        return EX_CONFIG  # fail closed: never claim work this host cannot isolate
    worker_id = os.environ.get("GWA_WORKER_ID") or socket.gethostname()
    try:
        isolation = isolation_mode()
        if not startup_preflight(isolation):
            return EX_CONFIG
        token = load_worker_token()
        client = _client(token)
        scrub_control_plane_environment()
        reset_work_root(work_root())
        # The Astro dependency set serves generative jobs only (bubblewrap).
        prepared = (
            prepare_dependencies(Path(os.environ.get("GWA_DEPENDENCY_ROOT", DEFAULT_DEPENDENCY_ROOT)))
            if isolation == "bubblewrap"
            else None
        )
    except (WorkerConfigError, DependencyPreparationError) as exc:
        logger.error("worker not started: %s", exc)
        return EX_CONFIG
    state.preflight_ok = True
    port = health_port()
    health = start_health_server(port, state) if port else None
    backoff = IDLE_SECONDS
    try:
        with client:
            while not state.stop.is_set():
                state.tick("idle")
                try:
                    worked = run_once(
                        client, worker_id=worker_id, prepared_dependencies=prepared, isolation=isolation, state=state
                    )
                    backoff = IDLE_SECONDS
                except WorkerConfigError as exc:
                    logger.error("worker stopping: %s", exc)
                    return EX_CONFIG
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("control plane unavailable (%s); retrying in %ds", type(exc).__name__, backoff)
                    if once:
                        return 1
                    state.stop.wait(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                    continue
                if once:
                    return 0
                if not worked:
                    state.stop.wait(IDLE_SECONDS)
            logger.info("worker stopped on request")
            return 0
    finally:
        state.tick("stopping")
        if health is not None:
            health.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry nothing we need
    if args.selftest:
        return selftest()
    if args.preflight:
        try:
            mode = isolation_mode()
        except WorkerConfigError as exc:
            print(json.dumps({"ready": False, "reason": str(exc)}))
            return 1
        try:
            process_protection.make_non_dumpable()
        except process_protection.ProcessProtectionError:
            pass  # reported as a failed check below
        report = worker_preflight.run_preflight(isolation=mode, work_root=work_root())
        print(report.to_json())
        return 0 if report.ok else 1
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    return serve(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
