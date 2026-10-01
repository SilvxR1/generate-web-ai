"""v0.2 R4.1/R4.2 — the isolated execution host's process.

    python -m app.worker --selftest   # readiness: can THIS host enforce R4?
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
    worker token            $CREDENTIALS_DIRECTORY/worker-token (systemd
                            LoadCredential=), else GWA_WORKER_TOKEN

Concurrency is exactly one job per process, by construction: the loop
claims, executes and reports one job before it claims the next, so a second
queued job stays QUEUED. Horizontal scaling later = more worker processes or
hosts pulling from the same queue (claims are atomic server-side).

Logs carry worker id, job id, attempt, durations and safe failure
categories only — never a token, the source, BusinessTruth, customer
content or the environment.
"""

import argparse
import json
import logging
import os
import shutil
import socket
import sys
import time
from pathlib import Path

import httpx

from app.creative.frontend_engine.dependencies import DependencyPreparationError, prepare_dependencies
from app.creative.frontend_engine.sandbox import SandboxError, SupervisedProcessRunner, detect_runner
from app.domain.enums import GenerationFailureKind, GenerationJobKind
from app.worker.executor import execute
from app.worker.protocol import MAX_EXPORT_SNAPSHOT_BYTES, ExecutionRequest, ExecutionResult
from app.worker.source_executor import execute_source_adaptation

logger = logging.getLogger("app.worker")
REQUIRED_LIMITS = ("wall_timeout", "cpu", "file_size", "tmp_size", "memory", "process_count")
IDLE_SECONDS = 10
MAX_BACKOFF_SECONDS = 300
RESULT_ATTEMPTS = 5
DEFAULT_DEPENDENCY_ROOT = "/var/lib/gwa-worker/deps"
# Permanent problems (host cannot isolate, credential missing/revoked, bad
# configuration): systemd must NOT restart-loop on these
# (RestartPreventExitStatus=78 in deploy/worker/gwa-worker.service).
EX_CONFIG = 78


class WorkerConfigError(Exception):
    """The worker is not configured to talk to the control plane."""


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
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials:
        path = Path(credentials) / "worker-token"
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    token = os.environ.get("GWA_WORKER_TOKEN", "").strip()
    if not token:
        raise WorkerConfigError("no worker token (LoadCredential=worker-token or GWA_WORKER_TOKEN)")
    return token


def _submit_result(client: httpx.Client, *, request: ExecutionRequest, job_token: str, result: ExecutionResult) -> str:
    """Retries transient failures only. The control plane accepts a result
    exactly once per job/attempt; a 409 after an earlier attempt that may
    have landed means it already did — never a second READY."""
    url = f"/internal/generation-worker/jobs/{request.job_id}/result"
    body = result.model_dump_json()
    for attempt in range(1, RESULT_ATTEMPTS + 1):
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
    client: httpx.Client, *, worker_id: str, prepared_dependencies: Path | None, isolation: str = "bubblewrap"
) -> bool:
    """Claims and processes at most one job. Returns False when idle."""
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
    if request.job_kind is GenerationJobKind.SOURCE_ADAPTATION:
        runner = SupervisedProcessRunner() if isolation == "supervised-process" else detect_runner()
        result = execute_source_adaptation(request, _download_source(client, request, body["job_token"]), runner=runner)
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
    outcome = _submit_result(client, request=request, job_token=body["job_token"], result=result)
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


def _client(token: str) -> httpx.Client:
    base = os.environ.get("GWA_API_BASE_URL", "").strip()
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
        raise WorkerConfigError("GWA_API_BASE_URL must be an https:// URL")
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(60.0, read=300.0),
    )


def serve(*, once: bool) -> int:
    if selftest() != 0:
        return EX_CONFIG  # fail closed: never claim work this host cannot isolate
    worker_id = os.environ.get("GWA_WORKER_ID") or socket.gethostname()
    try:
        isolation = isolation_mode()
        token = load_worker_token()
        client = _client(token)
        # The Astro dependency set serves generative jobs only (bubblewrap).
        prepared = (
            prepare_dependencies(Path(os.environ.get("GWA_DEPENDENCY_ROOT", DEFAULT_DEPENDENCY_ROOT)))
            if isolation == "bubblewrap"
            else None
        )
    except (WorkerConfigError, DependencyPreparationError) as exc:
        logger.error("worker not started: %s", exc)
        return EX_CONFIG
    backoff = IDLE_SECONDS
    with client:
        while True:
            try:
                worked = run_once(client, worker_id=worker_id, prepared_dependencies=prepared, isolation=isolation)
                backoff = IDLE_SECONDS
            except WorkerConfigError as exc:
                logger.error("worker stopping: %s", exc)
                return EX_CONFIG
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("control plane unavailable (%s); retrying in %ds", type(exc).__name__, backoff)
                if once:
                    return 1
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
            if once:
                return 0
            if not worked:
                time.sleep(IDLE_SECONDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines carry nothing we need
    if args.selftest:
        return selftest()
    return serve(once=args.once)


if __name__ == "__main__":
    sys.exit(main())
