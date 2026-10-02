"""R5.1.2 adversarial fixtures — NOT a pytest module (no `test_` prefix), run
as subprocesses by tests/test_r5_1_2_worker_proc_isolation.py so the real
PR_SET_DUMPABLE behaviour is exercised outside the pytest process.

worker_stub role: a stand-in worker. It carries a sentinel worker token in
its startup environment and a sentinel job token in memory, optionally
makes itself non-dumpable, emulates Railway's Yama ptrace_scope=0 (so the
control actually reproduces the production leak), then runs the hostile
probe as a same-UID child and prints its JSON verdict.

hostile role: a stand-in malicious build. Given the two sentinels, it walks
its ancestor PIDs and tries to recover either from each ancestor's
/proc/<pid>/environ, /proc/<pid>/cmdline and (where readable)
/proc/<pid>/mem. It reports, per ancestor, whether a sentinel was found or
why access failed. No files are written; sentinels come from argv only.
"""

import ctypes
import ctypes.util
import json
import os
import re
import subprocess
import sys

PR_SET_DUMPABLE = 4
PR_SET_PTRACER = 0x59616D61
PR_SET_PTRACER_ANY = ctypes.c_ulong(-1).value


def _libc():  # type: ignore[no-untyped-def]
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _scan_mem(pid: int, *sentinels: bytes) -> str:
    try:
        with open(f"/proc/{pid}/maps") as maps, open(f"/proc/{pid}/mem", "rb", 0) as mem:
            for line in maps:
                m = re.match(r"([0-9a-f]+)-([0-9a-f]+) (\S+)", line)
                if not m or "r" not in m.group(3):
                    continue
                a, b = int(m.group(1), 16), int(m.group(2), 16)
                if b - a > 256 * 1024**2:
                    continue
                try:
                    mem.seek(a)
                    chunk = mem.read(b - a)
                except OSError:
                    continue
                if any(s in chunk for s in sentinels):
                    return "LEAKED"
        return "clean"
    except OSError as exc:
        return type(exc).__name__


def hostile(env_sentinel: bytes, mem_sentinel: bytes) -> dict:
    out: dict[str, dict[str, str]] = {}
    pid = os.getppid()  # includes PID 1: in the container the worker IS PID 1
    while pid >= 1:
        entry: dict[str, str] = {}
        for name in ("environ", "cmdline"):
            try:
                data = open(f"/proc/{pid}/{name}", "rb").read()
                entry[name] = "LEAKED" if (env_sentinel in data or mem_sentinel in data) else "clean"
            except OSError as exc:
                entry[name] = type(exc).__name__
        entry["mem"] = _scan_mem(pid, env_sentinel, mem_sentinel)
        out[str(pid)] = entry
        if pid == 1:
            break
        try:
            parent = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError):
            break
        if parent == pid:
            break
        pid = parent
    return out


def worker_stub() -> None:
    import secrets

    mode = sys.argv[2]
    # Generated HERE, kept only in memory — never in this process's argv, so
    # the cmdline audit is meaningful (a real job token is likewise never
    # placed on the worker's command line).
    mem_sentinel = ("JOBTOKEN-" + secrets.token_hex(12)).encode()
    env_sentinel = os.environ["GWA_WORKER_TOKEN"].encode()
    # Keep the in-memory per-job token reachable so a readable /mem would find
    # it (proves the control, and that protection hides it too).
    _job_token_in_memory = bytearray(mem_sentinel)  # noqa: F841
    libc = _libc()
    libc.prctl(PR_SET_PTRACER, ctypes.c_ulong(PR_SET_PTRACER_ANY), 0, 0, 0)  # emulate Railway Yama=0
    if mode == "protect":
        from app.worker.process_protection import make_non_dumpable

        make_non_dumpable()
    os.environ.pop("GWA_WORKER_TOKEN", None)  # the R5.1 scrub (kept, defence in depth)
    result = subprocess.run(  # noqa: S603
        [sys.executable, __file__, "hostile", env_sentinel.decode(), mem_sentinel.decode()],
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip() or json.dumps({"error": result.stderr[-800:]}))


def init_stub() -> None:
    """R5.2: app.worker.init as PID-1 stand-in, in THIS process (so the Yama
    emulation applies to it), running the protected worker stub. `control`
    skips the init's own protection — what a stock (dumpable) init does."""
    mode = sys.argv[2]
    _libc().prctl(PR_SET_PTRACER, ctypes.c_ulong(PR_SET_PTRACER_ANY), 0, 0, 0)  # emulate Railway Yama=0
    from app.worker import init, process_protection

    if mode == "control":
        process_protection.make_non_dumpable = lambda: None  # type: ignore[assignment]
    sys.exit(init.run([], command=[sys.executable, __file__, "worker", "protect"]))


def orphan_maker() -> None:
    """Leaves an orphan (its shell parent exits at once), waits for the
    orphan to exit, then counts zombies whose parent is OUR parent."""
    import time

    subprocess.run(["sh", "-c", "sleep 0.3 & exit 0"], check=True)  # noqa: S603, S607
    time.sleep(1.5)
    parent = os.getppid()
    zombies = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            status = open(f"/proc/{entry}/status").read()
        except OSError:
            continue
        fields = dict(line.split(":\t", 1) for line in status.splitlines() if ":\t" in line)
        if fields.get("PPid", "").strip() == str(parent) and fields.get("State", "").startswith("Z"):
            zombies += 1
    print(json.dumps({"zombies_under_parent": zombies}))


def lazy_subreaper() -> None:
    """Control: a subreaper that waits only for its direct child (what
    `python -m app.worker` as PID 1 effectively did) — orphans stay zombies."""
    _libc().prctl(36, 1, 0, 0, 0)  # PR_SET_CHILD_SUBREAPER
    child = subprocess.Popen([sys.executable, __file__, "orphan_maker"])  # noqa: S603
    child.wait()


def reaping_init() -> None:
    from app.worker import init

    sys.exit(init.run([], command=[sys.executable, __file__, "orphan_maker"]))


if __name__ == "__main__":
    if sys.argv[1] == "hostile":
        print(json.dumps(hostile(sys.argv[2].encode(), sys.argv[3].encode())))
    elif sys.argv[1] == "worker":
        worker_stub()
    elif sys.argv[1] == "init":
        init_stub()
    elif sys.argv[1] == "orphan_maker":
        orphan_maker()
    elif sys.argv[1] == "lazy_subreaper":
        lazy_subreaper()
    elif sys.argv[1] == "reaping_init":
        reaping_init()
