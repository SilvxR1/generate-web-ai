"""v0.2 R4.1 — the isolated execution host's process.

    python -m app.worker --selftest   # readiness: can THIS host enforce R4?
    python -m app.worker --once       # claim, execute and report one job
    python -m app.worker              # loop (one job at a time)

Environment (the host's ONLY configuration — no platform secret):
    GWA_API_BASE_URL      e.g. https://api.example.com
    GWA_WORKER_TOKEN      the claim-only worker credential

Jobs run strictly one at a time: concurrency is bounded by construction
until a host is sized and proven for more.
"""

import argparse
import json
import logging
import os
import sys
import time

import httpx

from app.creative.frontend_engine.sandbox import SandboxError, detect_runner
from app.worker.executor import execute
from app.worker.protocol import ExecutionRequest

logger = logging.getLogger("app.worker")
REQUIRED_LIMITS = ("wall_timeout", "cpu", "file_size", "tmp_size", "memory", "process_count")
_IDLE_SECONDS = 10


def selftest() -> int:
    """Ready only if the sandbox can be created AND every required limit
    is enforced on this host (a host without a cgroup scope is not ready)."""
    try:
        runner = detect_runner()
    except SandboxError as exc:
        print(json.dumps({"ready": False, "reason": str(exc)}))
        return 1
    enforced = runner.limits_enforced()
    missing = [name for name in REQUIRED_LIMITS if not enforced.get(name)]
    print(json.dumps({"ready": not missing, "runner": runner.name, "limits_enforced": enforced, "missing": missing}))
    return 0 if not missing else 1


def run_once(client: httpx.Client) -> bool:
    response = client.post("/internal/generation-worker/claim")
    if response.status_code == 204:
        return False
    response.raise_for_status()
    body = response.json()
    request = ExecutionRequest.model_validate(body["request"])
    result = execute(request)
    client.post(
        f"/internal/generation-worker/jobs/{request.job_id}/result",
        content=result.model_dump_json(),
        headers={"Authorization": f"Bearer {body['job_token']}", "Content-Type": "application/json"},
    ).raise_for_status()
    logger.info("job %s reported: %s", request.job_id, result.status)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.selftest:
        return selftest()
    if selftest() != 0:
        return 1  # fail closed: never claim work this host cannot isolate
    client = httpx.Client(
        base_url=os.environ["GWA_API_BASE_URL"],
        headers={"Authorization": f"Bearer {os.environ['GWA_WORKER_TOKEN']}"},
        timeout=httpx.Timeout(60.0, read=300.0),
    )
    with client:
        while True:
            worked = run_once(client)
            if args.once:
                return 0
            if not worked:
                time.sleep(_IDLE_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
