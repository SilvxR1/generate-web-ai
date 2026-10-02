"""R5.2 — the worker container's init (app.worker.init).

It must reap orphaned build descendants (Chromium helpers were left as
zombies in production), forward shutdown signals, return the worker's exit
status, and — unlike a stock init such as tini — keep the startup
environment it holds (GWA_WORKER_TOKEN) unreadable to same-UID builds.
Probes run as real subprocesses (tests/r5_1_2_procfs_probe.py).
"""

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from app.worker import init, preflight, process_protection

API_ROOT = Path(__file__).resolve().parents[1]
PROBE = API_ROOT / "tests" / "r5_1_2_procfs_probe.py"

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl/procfs are Linux-only")


def _env(**extra: str) -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "PYTHONPATH": str(API_ROOT), "HOME": os.environ.get("HOME", "/tmp"), **extra}


def _probe(role: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(PROBE), role, *args], env=_env(**env), capture_output=True, text=True, timeout=120
    )


# --- Reaping --------------------------------------------------------------------------------------


def test_init_reaps_orphaned_descendants_and_the_control_proves_the_probe():
    control = _probe("lazy_subreaper")
    assert control.returncode == 0, control.stderr
    assert json.loads(control.stdout.strip())["zombies_under_parent"] >= 1  # the production symptom

    reaped = _probe("reaping_init")
    assert reaped.returncode == 0, reaped.stderr
    assert json.loads(reaped.stdout.strip())["zombies_under_parent"] == 0


# --- procfs protection of the init itself -----------------------------------------------------------


def _ancestors(mode: str) -> list[dict]:
    result = _probe("init", mode, GWA_WORKER_TOKEN="WORKERTOKEN-" + uuid.uuid4().hex)
    assert result.returncode == 0, result.stderr
    return list(json.loads(result.stdout.strip()).values())


def test_a_dumpable_init_would_leak_the_token_which_is_why_tini_is_not_used():
    worker, init_process = _ancestors("control")[:2]
    assert worker["environ"] == "PermissionError", worker  # the worker still protects itself
    assert init_process["environ"] == "LEAKED", init_process  # the hole a stock init re-opens


def test_the_init_hides_its_environment_and_memory_from_a_same_uid_build():
    report = _ancestors("protect")
    for entry in report:
        assert entry["environ"] != "LEAKED" and entry["mem"] != "LEAKED", entry
        assert entry["cmdline"] == "clean", entry
    worker, init_process = report[:2]
    assert worker["environ"] == "PermissionError" and init_process["environ"] == "PermissionError", report


# --- Signals and exit status ------------------------------------------------------------------------


def _init_with(command: list[str]) -> subprocess.Popen[str]:
    code = f"import sys; from app.worker.init import run; sys.exit(run([], command={command!r}))"
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", code], env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def test_sigterm_is_forwarded_and_the_workers_exit_status_is_returned():
    worker = (
        "import signal, sys, time; signal.signal(signal.SIGTERM, lambda *a: sys.exit(7)); "
        "print('ready', flush=True); time.sleep(60)"
    )
    process = _init_with([sys.executable, "-c", worker])
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=30) == 7


@pytest.mark.parametrize(
    ("script", "expected"),
    [("import sys; sys.exit(0)", 0), ("import sys; sys.exit(78)", 78), ("import os; os.kill(os.getpid(), 9)", 137)],
)
def test_exit_codes_pass_through(script, expected):
    process = _init_with([sys.executable, "-c", script])
    assert process.wait(timeout=30) == expected  # EX_CONFIG (78) keeps meaning "do not restart-loop"


def test_the_init_refuses_to_start_unprotected(monkeypatch):
    def fail() -> None:
        raise process_protection.ProcessProtectionError("no prctl here")

    monkeypatch.setattr(process_protection, "make_non_dumpable", fail)
    started = time.monotonic()
    assert init.run([], command=[sys.executable, "-c", "raise SystemExit(0)"]) == init.EX_CONFIG
    assert time.monotonic() - started < 5  # refused before starting anything


def test_exit_code_helper():
    assert init.exit_code(0) == 0
    assert init.exit_code(78 << 8) == 78
    assert init.exit_code(signal.SIGKILL) == 128 + signal.SIGKILL


# --- Preflight -------------------------------------------------------------------------------------


def test_preflight_fails_closed_when_pid1_environment_is_readable(tmp_path):
    (tmp_path / "1").mkdir()
    readable = tmp_path / "1" / "environ"
    readable.write_bytes(b"GWA_WORKER_TOKEN=x\0")
    ok, detail = preflight.init_protection(str(tmp_path))
    assert ok is False and "readable" in detail
    readable.chmod(0)
    if os.geteuid() != 0:  # root ignores file modes
        assert preflight.init_protection(str(tmp_path))[0] is True
    assert preflight.init_protection(str(tmp_path / "missing"))[0] is True
