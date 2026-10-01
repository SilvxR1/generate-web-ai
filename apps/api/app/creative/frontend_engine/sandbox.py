"""v0.2 R4 — the untrusted build zone.

`astro build` executes generated code (component frontmatter, bundling of
generated TS/JS). R4's principle: untrusted generated code never executes
inside the trusted API process's reach or with access to platform secrets.
A SandboxRunner is the ONLY way build.py runs that step.

BubblewrapRunner (the only implementation) wraps the command in
`bwrap --unshare-all` — new user, mount, PID, network, IPC, UTS and cgroup
namespaces — with:

- environment: `--clearenv` plus the caller's explicit allowlist only;
- filesystem: an empty root with read-only /usr, /lib*, /bin and the Node.js
  toolchain, fresh /proc, /dev and a size-capped /tmp, and the job's own
  workspace bound read-write at /workspace. The API's home, the repository,
  /etc, other jobs' workspaces and other processes are simply absent;
- network: a fresh network namespace with only loopback — no route to
  the host's localhost services, the internet or a metadata address;
- process: PID namespace; `--die-with-parent` plus a process-group kill
  tear the whole tree down on timeout;
- resources: wall-clock timeout, RLIMIT_CPU/FSIZE/NOFILE, a size-capped
  /tmp, and memory/process count through a cgroup scope
  (`systemd-run --user --scope`) when the host provides one — otherwise
  RLIMIT_AS for memory and the process count is reported as NOT enforced
  (see `limits_enforced`).

Fail closed: if bwrap is missing or the kernel refuses unprivileged user
namespaces, `detect_runner()` raises SandboxUnavailableError and nothing is
built — there is no unsandboxed fallback. Whether a given production host
can pass `detect_runner()` is an infrastructure question this module does
not answer (see docs/v0.2-generative-website-architecture.md, R4).
"""

import logging
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from app.publishing.errors import WebsitePublisherError

logger = logging.getLogger(__name__)

SANDBOX_WORKSPACE = "/workspace"
_OUTPUT_TAIL_BYTES = 2000
_HOST_PATH = "/usr/bin:/bin"


class SandboxError(WebsitePublisherError):
    """The sandboxed step failed, timed out or exceeded a limit."""


class SandboxUnavailableError(SandboxError):
    """This host cannot enforce the untrusted build zone — fail closed."""


@dataclass(frozen=True)
class SandboxLimits:
    wall_timeout_seconds: int = 120
    cpu_seconds: int = 300
    memory_bytes: int = 3 * 1024**3
    max_processes: int = 256
    max_file_bytes: int = 256 * 1024**2  # RLIMIT_FSIZE: largest single file, incl. captured output
    tmp_bytes: int = 512 * 1024**2
    max_open_files: int = 4096
    # cgroup CPU bandwidth for the whole job tree (with a cgroup scope);
    # RLIMIT_CPU above still bounds each process's total CPU time.
    cpu_quota_percent: int = 200
    # Without a cgroup scope, memory falls back to RLIMIT_AS. Chromium
    # reserves far more virtual address space than it uses, so Visual QA
    # opts out; memory is then reported NOT enforced on such a host.
    address_space_fallback: bool = True


def _toolchain_roots() -> tuple[Path, ...]:
    """Node.js installation prefix(es) outside /usr (nvm, CI tool caches),
    bound read-only so `node` resolves inside the sandbox."""
    node = shutil.which("node")
    if node is None:
        return ()
    roots = {Path(node).resolve().parent.parent, Path(node).parent.parent}
    return tuple(sorted(r for r in roots if not str(r).startswith(("/usr", "/bin", "/lib"))))


class SandboxRunner:
    name = "abstract"

    def run(
        self,
        argv: list[str],
        *,
        workspace: Path,
        env: dict[str, str],
        limits: SandboxLimits,
        step: str,
        ro_binds: tuple[tuple[str, str], ...] = (),
    ) -> None:
        raise NotImplementedError

    def limits_enforced(self, limits: SandboxLimits | None = None) -> dict[str, bool]:
        raise NotImplementedError


class BubblewrapRunner(SandboxRunner):
    name = "bubblewrap"

    def __init__(self, *, bwrap: str, systemd_run: str | None) -> None:
        self._bwrap = bwrap
        self._systemd_run = systemd_run
        self._toolchains = _toolchain_roots()

    def limits_enforced(self, limits: SandboxLimits | None = None) -> dict[str, bool]:
        cgroup = self._systemd_run is not None
        return {
            "wall_timeout": True,
            "cpu": True,
            "file_size": True,
            "tmp_size": True,
            "memory": cgroup or (limits or SandboxLimits()).address_space_fallback,  # MemoryMax, else RLIMIT_AS
            "process_count": cgroup,
        }

    def command(
        self,
        argv: list[str],
        *,
        workspace: Path,
        env: dict[str, str],
        limits: SandboxLimits,
        ro_binds: tuple[tuple[str, str], ...] = (),
    ) -> list[str]:
        cmd = [
            self._bwrap,
            "--unshare-all",
            "--unshare-user",  # required, not "-try": fail if the kernel refuses
            "--die-with-parent",
            "--new-session",
            "--disable-userns",
            "--hostname",
            "gwa-build",
            "--clearenv",
        ]
        for key, value in env.items():
            cmd += ["--setenv", key, value]
        cmd += ["--ro-bind", "/usr", "/usr"]
        for system_dir in ("/bin", "/lib", "/lib64", "/sbin"):
            cmd += ["--ro-bind-try", system_dir, system_dir]
        for root in self._toolchains:
            cmd += ["--ro-bind", str(root), str(root)]
        cmd += ["--proc", "/proc", "--dev", "/dev", "--size", str(limits.tmp_bytes), "--tmpfs", "/tmp"]
        cmd += ["--bind", str(workspace), SANDBOX_WORKSPACE]
        # After the workspace bind, so a target inside /workspace (e.g. the
        # prepared node_modules) overlays it read-only. Never a secret.
        for source, target in ro_binds:
            cmd += ["--ro-bind", source, target]
        cmd += ["--chdir", SANDBOX_WORKSPACE, "--", *argv]
        if self._systemd_run is None:
            return cmd
        return [
            self._systemd_run,
            "--user",
            "--scope",
            "--quiet",
            "--collect",
            "-p",
            f"MemoryMax={limits.memory_bytes}",
            "-p",
            "MemorySwapMax=0",
            "-p",
            f"TasksMax={limits.max_processes}",
            "-p",
            f"CPUQuota={limits.cpu_quota_percent}%",
            "--",
            *cmd,
        ]

    def run(
        self,
        argv: list[str],
        *,
        workspace: Path,
        env: dict[str, str],
        limits: SandboxLimits,
        step: str,
        ro_binds: tuple[tuple[str, str], ...] = (),
    ) -> None:
        cmd = self.command(argv, workspace=workspace, env=env, limits=limits, ro_binds=ro_binds)
        use_rlimit_as = self._systemd_run is None and limits.address_space_fallback

        def _limit() -> None:  # in the child, before exec
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_file_bytes, limits.max_file_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))
            if use_rlimit_as:
                resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))

        # Output goes to a file bounded by RLIMIT_FSIZE, never into API memory.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=_launcher_env(),
                preexec_fn=_limit,  # noqa: PLW1509 — per-child rlimits
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=limits.wall_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_tree(process)
                raise SandboxError(f"{step} timed out after {limits.wall_timeout_seconds}s") from exc
            except BaseException:
                _kill_tree(process)  # worker shutdown: never leave the build running
                raise
            if returncode != 0:
                raise SandboxError(f"{step} failed (exit {returncode}): {_tail(output)}")


class SupervisedProcessRunner(SandboxRunner):
    """R5 — NOT a sandbox. For operator-imported, owner-reviewed sources on
    a worker host that cannot create namespaces (e.g. a plain container).

    What it does enforce: a separate child process in its own session
    (process-group kill on timeout), `cwd` = the job workspace, an
    environment built ONLY from the caller's allowlist (the worker's own
    credential is never passed), RLIMIT_CPU/FSIZE/NOFILE and a wall-clock
    timeout. What it does NOT enforce, and says so in `limits_enforced`:
    filesystem, network or PID isolation, a tmp size cap, a process-count
    limit or memory (RLIMIT_AS breaks modern bundlers' thread pools — Vite's
    Rolldown cannot start under it; memory is the worker container's limit). Its security rests on the
    worker host holding no platform secret and having no publish authority
    (the control plane re-validates every byte it returns) — and on the
    source having been reviewed by a human. It is never used for
    AI-generated code: the control plane only gives a supervised-process
    worker SUPERVISED_SOURCE jobs, and rejects any untrusted result not
    built by bubblewrap.
    """

    name = "supervised-process"

    def __init__(self) -> None:
        # R5.1 telemetry: peak RSS (kB) of each finished step's process tree
        # (wait4 rusage: the step and every descendant it waited for).
        self.step_peak_rss_kb: dict[str, int] = {}

    def limits_enforced(self, limits: SandboxLimits | None = None) -> dict[str, bool]:
        return {
            "wall_timeout": True,
            "cpu": True,
            "file_size": True,
            "tmp_size": False,
            "memory": False,
            "process_count": False,
            "filesystem_isolation": False,
            "network_isolation": False,
            "pid_isolation": False,
        }

    def run(
        self,
        argv: list[str],
        *,
        workspace: Path,
        env: dict[str, str],
        limits: SandboxLimits,
        step: str,
        ro_binds: tuple[tuple[str, str], ...] = (),
    ) -> None:
        from app.worker.preflight import forbidden_environment  # noqa: PLC0415 — avoids an import cycle

        # Defense in depth: the child environment is the caller's allowlist,
        # never os.environ — and it may not carry a platform credential.
        leaked = forbidden_environment(env) + [name for name in env if name.startswith("GWA_")]
        if leaked:
            raise SandboxError(f"{step}: refusing a child environment carrying {sorted(set(leaked))}")
        # Sandbox mount points in PATH (e.g. /opt/bun/bin) map back to the
        # host directories the caller would have bound.
        path = env.get("PATH", _HOST_PATH)
        for host, inside in ro_binds:
            path = path.replace(inside, host)

        def _limit() -> None:  # in the child, before exec
            resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
            resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_file_bytes, limits.max_file_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))

        executable = shutil.which(argv[0], path=path) or argv[0]
        # A private HOME/TMPDIR per step, next to the job's workspace (never
        # the host's shared /tmp, which other jobs' steps also see), removed
        # with the step.
        with (
            tempfile.TemporaryDirectory(prefix="gwa-step-home-", dir=workspace.parent) as home,
            tempfile.TemporaryFile() as output,
        ):
            child_env = {**env, "PATH": path, "HOME": home, "TMPDIR": home}
            process = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
                [executable, *argv[1:]],
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=child_env,
                preexec_fn=_limit,  # noqa: PLW1509 — per-child rlimits
                start_new_session=True,
            )
            try:
                returncode, peak_kb = _wait_with_rusage(process, timeout=limits.wall_timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _kill_tree(process)
                raise SandboxError(f"{step} timed out after {limits.wall_timeout_seconds}s") from exc
            except BaseException:
                _kill_tree(process)  # worker shutdown: never leave the build running
                raise
            finally:
                _kill_group(process)  # descendants that outlived the step (daemons) die with it
            self.step_peak_rss_kb[step] = peak_kb
            if returncode != 0:
                raise SandboxError(f"{step} failed (exit {returncode}): {_tail(output)}")


def _wait_with_rusage(process: "subprocess.Popen[bytes]", *, timeout: float) -> tuple[int, int]:
    """Popen.wait with a timeout, but reaping through wait4 so the step's
    peak RSS (kB, the process and its waited-for descendants) is known."""
    deadline = time.monotonic() + timeout
    delay = 0.01
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid == process.pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return process.returncode, int(usage.ru_maxrss)
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(delay)
        delay = min(delay * 2, 0.25)


def _kill_group(process: "subprocess.Popen[bytes]") -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _launcher_env() -> dict[str, str]:
    """What bwrap/systemd-run themselves receive: a PATH and, for the cgroup
    scope, the user session bus location — never a platform secret. bwrap
    then `--clearenv`s before exec'ing untrusted code anyway."""
    session = {k: os.environ[k] for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if k in os.environ}
    return {"PATH": _HOST_PATH, **session}


def _tail(output: IO[bytes]) -> str:
    output.seek(0, os.SEEK_END)
    output.seek(max(0, output.tell() - _OUTPUT_TAIL_BYTES))
    return output.read().decode("utf-8", errors="replace")


def _kill_tree(process: "subprocess.Popen[bytes]") -> None:
    _kill_group(process)
    if process.returncode is None:
        process.wait()


def _works(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=15, env=_launcher_env()).returncode == 0  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect_runner() -> SandboxRunner:
    """Proves — by actually creating the namespaces — that this host can
    enforce the build zone; raises SandboxUnavailableError otherwise."""
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise SandboxUnavailableError("bubblewrap is not installed — refusing to run untrusted generated code.")
    systemd_run = shutil.which("systemd-run")
    scope_probe = ["--user", "--scope", "--quiet", "--collect", "-p", "TasksMax=8", "--", "/usr/bin/true"]
    if systemd_run is not None and not _works([systemd_run, *scope_probe]):
        systemd_run = None
    runner = BubblewrapRunner(bwrap=bwrap, systemd_run=systemd_run)
    with tempfile.TemporaryDirectory(prefix="gwa-sandbox-probe-") as probe_dir:
        probe = runner.command(["/usr/bin/true"], workspace=Path(probe_dir), env={}, limits=SandboxLimits())
        if not _works(probe):
            raise SandboxUnavailableError(
                "unprivileged user/network namespaces are unavailable — refusing to run untrusted generated code."
            )
    logger.info("generative build sandbox: %s limits_enforced=%s", runner.name, runner.limits_enforced())
    return runner
