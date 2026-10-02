"""R5.2 — the worker container's init: reap orphans without exposing the token.

    python -m app.worker.init [worker args...]   # runs: python -m app.worker [worker args...]

Why not `tini`: Railway hands `GWA_WORKER_TOKEN` to PID 1's startup
environment. A stock init keeps that environment in a DUMPABLE process of the
same UID as the builds, so a same-UID build could read it from
/proc/1/environ — exactly the R5.1.2 defect. This init therefore:

1. makes itself non-dumpable before anything else (app.worker.process_protection;
   refuses to start, EX_CONFIG, if it cannot);
2. marks itself a child subreaper (PR_SET_CHILD_SUBREAPER), so orphaned
   descendants are re-parented to it even when it is not PID 1;
3. starts the worker (`python -m app.worker`, which protects itself as before);
4. forwards SIGTERM/SIGINT/SIGHUP/SIGQUIT to the worker (graceful shutdown is
   unchanged: the worker kills its build tree and reports);
5. reaps EVERY child that exits — adopted orphans (e.g. Chromium helpers)
   included — and exits with the worker's own exit status.

It never reads, logs or forwards anything but the environment it was given,
runs as the image's non-root user, and needs no capability.
"""

import ctypes
import ctypes.util
import os
import signal
import subprocess
import sys

from app.worker import process_protection

EX_CONFIG = 78
PR_SET_CHILD_SUBREAPER = 36
FORWARDED = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT)


def _set_child_subreaper() -> None:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    if int(libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")


def exit_code(status: int) -> int:
    """The shell convention: the exit code, or 128 + the terminating signal."""
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.waitstatus_to_exitcode(status)


def _forward(pid: int, signum: int) -> None:
    try:
        os.kill(pid, signum)
    except ProcessLookupError:
        pass


def run(argv: list[str], *, command: list[str] | None = None) -> int:
    """`command` exists for tests only; the container always runs the worker."""
    try:
        process_protection.make_non_dumpable()
        _set_child_subreaper()
    except (process_protection.ProcessProtectionError, OSError) as exc:
        print(f"gwa-worker-init: refusing to start: {exc}", file=sys.stderr, flush=True)
        return EX_CONFIG

    worker = subprocess.Popen(command or [sys.executable, "-m", "app.worker", *argv])  # noqa: S603 — fixed argv
    for sig in FORWARDED:
        signal.signal(sig, lambda signum, _frame: _forward(worker.pid, signum))

    while True:
        try:
            pid, status = os.wait()
        except ChildProcessError:
            return 1  # no children left without seeing the worker exit (not expected)
        if pid == worker.pid:
            worker.returncode = exit_code(status)  # reaped here; keep Popen consistent
            return worker.returncode
        # Any other pid: an orphaned descendant adopted by this subreaper — reaped.


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
