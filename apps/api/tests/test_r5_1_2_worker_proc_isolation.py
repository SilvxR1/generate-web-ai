"""R5.1.2 — a same-UID build process must not recover the worker's
credentials through procfs. The probe runs in real subprocesses
(tests/r5_1_2_procfs_probe.py), emulating Railway's Yama ptrace_scope=0.

The control (protection OFF) must LEAK, or the regression would be looking
at the wrong PID/path and could pass trivially. The fix (protection ON)
must leak nothing. R5.1's own tests only checked process.env / os.environ,
which already passed while the defect was live — so these inspect the
PARENT worker through procfs instead.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.worker import process_protection

API_ROOT = Path(__file__).resolve().parent.parent
PROBE = API_ROOT / "tests" / "r5_1_2_procfs_probe.py"

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="procfs isolation is Linux-only")


def _run_probe(mode: str) -> dict:
    env_sentinel = "WORKERTOKEN-" + uuid.uuid4().hex
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(PROBE), "worker", mode],
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(API_ROOT),
            "GWA_WORKER_TOKEN": env_sentinel,
            "HOME": os.environ.get("HOME", "/tmp"),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def _worker_ancestor(report: dict) -> dict:
    """The nearest ancestor that is the worker stub: the one the control
    leaks through. It is the hostile process's direct parent."""
    assert report, report
    return next(iter(report.values()))


def test_control_without_protection_leaks_the_worker_secrets_through_procfs():
    report = _run_probe("control")
    worker = _worker_ancestor(report)
    assert worker["environ"] == "LEAKED", worker  # the exact production defect
    assert worker["mem"] == "LEAKED", worker  # in-memory job token too (Yama=0)


def test_non_dumpable_worker_hides_environ_and_memory_from_a_same_uid_build():
    report = _run_probe("protect")
    for pid, entry in report.items():
        assert entry["environ"] != "LEAKED", (pid, entry)
        assert entry["mem"] != "LEAKED", (pid, entry)
    worker = _worker_ancestor(report)
    assert worker["environ"] == "PermissionError", worker
    assert worker["mem"] in ("PermissionError", "FileNotFoundError"), worker


def test_no_worker_secret_appears_in_any_ancestor_command_line():
    # argv/cmdline is world-readable even when non-dumpable, so no credential
    # may ever be placed there (R5.1.2 audit).
    for mode in ("control", "protect"):
        report = _run_probe(mode)
        for pid, entry in report.items():
            assert entry["cmdline"] == "clean", (mode, pid, entry)


def test_make_non_dumpable_is_verified_and_idempotent():
    # In a child, so the shared pytest process stays dumpable for other tests.
    assert not process_protection.is_non_dumpable()  # pytest itself starts dumpable
    pid = os.fork()
    if pid == 0:
        ok = False
        try:
            process_protection.make_non_dumpable()
            process_protection.make_non_dumpable()  # idempotent
            ok = process_protection.is_non_dumpable()
        finally:
            os._exit(0 if ok else 1)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert not process_protection.is_non_dumpable()  # parent unaffected
