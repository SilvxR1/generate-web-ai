"""R5.1.2 — keep same-UID build processes out of the worker's own process.

In supervised-process mode the worker and everything it runs (bun, Vite,
the export's own scripts, Chromium) share one UID. R5.1 removed the token
from Python's `os.environ`, but the kernel keeps the process's STARTUP
environment, and procfs exposes it (and, where the kernel's Yama
`ptrace_scope` is 0 — as on Railway — the process memory) to any process
of the same UID. Found on the real Railway worker.

`PR_SET_DUMPABLE=0` makes the kernel treat the worker like a privileged
process: its `/proc/<pid>/{environ,mem,maps,fd,...}` become inaccessible to
other processes without CAP_SYS_PTRACE, and ptrace attach is refused. The
flag is NOT inherited across execve, so children (which never receive a
credential: their environments are explicit allowlists) stay ordinary.

What it does not do: it is not a sandbox. Same-UID processes still see
that the worker exists (`/proc/<pid>/cmdline`, `stat`), share the
filesystem and network, and can signal it. See
docs/r5-1-railway-build-worker.md.
"""

import ctypes
import ctypes.util
import sys
from typing import Any

PR_GET_DUMPABLE = 3
PR_SET_DUMPABLE = 4


class ProcessProtectionError(Exception):
    """The worker could not make itself non-dumpable — it must not start."""


def _prctl() -> Any:
    if not sys.platform.startswith("linux"):
        raise ProcessProtectionError("process protection requires Linux (prctl)")
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    return prctl


def is_non_dumpable() -> bool:
    try:
        return int(_prctl()(PR_GET_DUMPABLE, 0, 0, 0, 0)) == 0
    except (ProcessProtectionError, OSError, AttributeError):
        return False


def make_non_dumpable() -> None:
    """Sets and VERIFIES the flag; raises ProcessProtectionError otherwise."""
    try:
        prctl = _prctl()
        if int(prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)) != 0:
            raise ProcessProtectionError(f"prctl(PR_SET_DUMPABLE, 0) failed (errno {ctypes.get_errno()})")
    except (OSError, AttributeError) as exc:
        raise ProcessProtectionError(f"prctl unavailable: {type(exc).__name__}") from exc
    if not is_non_dumpable():
        raise ProcessProtectionError("the worker is still dumpable after PR_SET_DUMPABLE")
