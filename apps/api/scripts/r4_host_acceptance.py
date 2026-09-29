#!/usr/bin/env python3
"""v0.2 R4.2 — production execution-host acceptance.

Run ON the candidate worker VM, as the worker user, inside the worker's own
service environment (see deploy/worker/gwa-worker-acceptance.service):

    sudo systemctl start gwa-worker-acceptance.service
    journalctl -u gwa-worker-acceptance.service -o cat | tail -40

PASS requires ALL of:
  1. not running as root;
  2. host probes: bubblewrap installed; unprivileged user+mount, network and
     PID namespaces create; cgroup v2 mounted and delegated; a user cgroup
     scope accepts MemoryMax/TasksMax/CPUQuota;
  3. `python -m app.worker --selftest` ready (every limit enforced);
  4. the R4, R4.1 and R4.2 malicious-fixture suites: every mapped security
     dimension has all of its tests present and passing, and NOTHING is
     skipped or errored (GWA_ACCEPTANCE=1 turns host-capability skips into
     failures).

Prints one line per check, a JSON summary, and finally exactly one of
R4_HOST_ACCEPTANCE=PASS / R4_HOST_ACCEPTANCE=FAIL; exits 0 only on PASS.
Makes no call to the production API, the provider or any paid service.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET  # noqa: S405 — parses pytest's own local output only
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "tests/test_v0_2_r4_isolated_worker.py",
    "tests/test_v0_2_r4_1_execution_host.py",
    "tests/test_v0_2_r4_2_worker_deployment.py",
)
# Security dimension -> tests that must ALL be present and pass.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "environment": (
        "test_platform_secrets_in_the_api_environment_never_reach_generated_code",
        "test_the_execution_hosts_own_credential_never_reaches_generated_code",
    ),
    "filesystem": (
        "test_generated_code_cannot_read_outside_its_workspace",
        "test_generated_code_cannot_write_outside_its_workspace",
        "test_prepared_dependencies_are_read_only_to_generated_code",
    ),
    "network": ("test_network_is_denied_local_services_external_hosts_metadata_and_dns",),
    "process": (
        "test_platform_secrets_in_the_api_environment_never_reach_generated_code",
        "test_a_process_explosion_is_contained_and_leaves_nothing_behind",
    ),
    "cpu": ("test_cpu_time_is_bounded",),
    "memory": ("test_memory_is_capped",),
    "pids": ("test_process_count_is_capped_by_the_cgroup",),
    "timeout": ("test_an_infinite_build_is_killed_at_the_wall_clock_limit",),
    "disk": (
        "test_excessive_output_is_capped",
        "test_scratch_disk_is_capped",
        "test_candidate_output_is_bounded",
    ),
    "cleanup": (
        "test_the_execution_hosts_own_credential_never_reaches_generated_code",
        "test_workspaces_are_removed_after_a_failed_build",
        "test_workspaces_are_removed_after_a_timed_out_build",
    ),
    "cross_job": ("test_generated_code_cannot_reach_another_jobs_workspace",),
    "visual_qa": (
        "test_positive_control_unsandboxed_chromium_does_reach_host_services",
        "test_sandboxed_visual_qa_network_namespace_alone_denies_everything",
        "test_sandboxed_visual_qa_serves_only_the_businesss_own_assets",
        "test_visual_qa_fails_closed_without_a_sandbox",
    ),
    "trusted_intake": (
        "test_a_malicious_host_cannot_bypass_the_truth_contract",
        "test_security_headers_are_never_taken_from_the_host",
        "test_a_tampered_candidate_is_rejected_and_never_stored",
    ),
}


def _ok(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return False


def host_probes() -> dict[str, bool]:
    uid = os.getuid()
    user_cgroup = Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers")
    delegated = set(user_cgroup.read_text().split()) if user_cgroup.is_file() else set()
    scope = [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "-p", "MemoryMax=256M", "-p", "TasksMax=32", "-p", "CPUQuota=100%", "--", "/usr/bin/true",
    ]  # fmt: skip
    return {
        "not_root": uid != 0,
        "bwrap_installed": shutil.which("bwrap") is not None,
        "userns_mountns": _ok(["unshare", "--user", "--map-root-user", "--mount", "true"]),
        "userns_net_pid": _ok(["unshare", "--user", "--map-root-user", "--net", "--pid", "--fork", "true"]),
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        "cgroup_delegated_memory_pids_cpu": {"memory", "pids", "cpu"} <= delegated,
        "cgroup_scope_limits": shutil.which("systemd-run") is not None and _ok(scope),
    }


def selftest() -> tuple[bool, str]:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "app.worker", "--selftest"], cwd=API_ROOT, capture_output=True, text=True, timeout=120
    )
    lines = done.stdout.strip().splitlines()
    return done.returncode == 0, (lines[-1] if lines else "")


def run_suites() -> tuple[dict[str, str], dict[str, int]]:
    """{test name: passed|failed|error|skipped} from JUnit XML — the
    authoritative record, not console text."""
    with tempfile.TemporaryDirectory(prefix="gwa-acceptance-") as tmp:
        junit = Path(tmp) / "junit.xml"
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *SUITES],
            cwd=API_ROOT,
            env={**os.environ, "GWA_ACCEPTANCE": "1"},
            timeout=3600,
        )
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        if not junit.is_file():
            counts["errors"] = 1
            return {}, counts
        outcomes: dict[str, str] = {}
        for case in ET.parse(junit).getroot().iter("testcase"):  # noqa: S314 — our own pytest output
            name = case.get("name", "").split("[", 1)[0]
            if case.find("skipped") is not None:
                outcome, key = "skipped", "skipped"
            elif case.find("failure") is not None:
                outcome, key = "failed", "failures"
            elif case.find("error") is not None:
                outcome, key = "error", "errors"
            else:
                outcome, key = "passed", ""
            counts["tests"] += 1
            if key:
                counts[key] += 1
            if outcomes.get(name, "passed") == "passed":
                outcomes[name] = outcome  # a parametrized test passes only if every case passes
        return outcomes, counts


def main() -> int:
    print(f"== host {platform.node()} {platform.release()} uid={os.getuid()}")
    probes = host_probes()
    for name, passed in probes.items():
        print(f"PROBE {name}={'PASS' if passed else 'FAIL'}")
    if not probes["not_root"]:
        print("R4_HOST_ACCEPTANCE=FAIL (must run as the unprivileged worker user, never root)")
        return 1

    ready, selftest_line = selftest()
    print(f"SELFTEST {'PASS' if ready else 'FAIL'} {selftest_line}")

    outcomes, counts = run_suites()
    dimensions: dict[str, bool] = {}
    for dimension, tests in DIMENSIONS.items():
        dimensions[dimension] = all(outcomes.get(test) == "passed" for test in tests)
        missing = [t for t in tests if t not in outcomes]
        verdict = "PASS" if dimensions[dimension] else "FAIL"
        print(f"DIMENSION {dimension}={verdict}" + (f" missing={missing}" if missing else ""))

    clean = counts["tests"] > 0 and counts["failures"] == counts["errors"] == counts["skipped"] == 0
    passed = all(probes.values()) and ready and clean and all(dimensions.values())
    print("SUMMARY " + json.dumps({"probes": probes, "selftest": ready, "suite": counts, "dimensions": dimensions}))
    if not passed:
        reasons = [k for k, v in probes.items() if not v]
        reasons += [] if ready else ["selftest"]
        reasons += [] if clean else [f"suite:{counts}"]
        reasons += [f"dimension:{k}" for k, v in dimensions.items() if not v]
        print(f"R4_HOST_ACCEPTANCE=FAIL ({', '.join(reasons)})")
        return 1
    print("R4_HOST_ACCEPTANCE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
