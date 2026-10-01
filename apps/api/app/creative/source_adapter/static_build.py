"""StaticBuild (H1): install and build an exported Bun/Vite project.

Two zones, mirroring R4.2 (docs/v0.2-generative-website-architecture.md):

1. prepare_dependencies — TRUSTED, host network, NO code execution:
   `bun install --ignore-scripts` with a from-scratch environment (no
   platform secret can be read, so none can be sent to a registry). The
   inputs bun reads are validated first: plain registry semver dependency
   specs only, every lockfile package resolved from the default registry,
   no `.npmrc`, no `trustedDependencies`, and a bunfig.toml limited to known
   harmless keys (bunfig can redirect the registry or read tokens from the
   environment).
2. build_in_sandbox — UNTRUSTED, the existing R4 BubblewrapRunner: no
   network, cleared environment, empty root with read-only system dirs,
   Node.js and the bun binary, the workspace as the only writable path,
   wall/CPU/memory/file limits. This is where the exported code executes
   (the adapter's BuildSpec steps: e.g. its postinstall check and its own
   `bun run build`).
"""

import json
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from app.creative.frontend_engine.sandbox import SandboxLimits, SandboxRunner
from app.creative.source_adapter.records import AdapterError

INSTALL_TIMEOUT_SECONDS = 300
BUILD_LIMITS = SandboxLimits(wall_timeout_seconds=600, cpu_seconds=1200, memory_bytes=3 * 1024**3)
_BUN_IN_SANDBOX = "/opt/bun/bin"
# Plain registry semver: 1.2.3, ^1.2.3, ~1.2, >=1 <2, 1.x, 3.0.260429-beta — never a URL/git/file/alias.
_SEMVER_SPEC = re.compile(r"^[\s\d.xX*^~<>=|+a-zA-Z-]+$")
_FORBIDDEN_SPEC = re.compile(r"(?:^|\s)(?:workspace:|file:|link:|git|github:|https?:|npm:|portal:|patch:)|/|#")
_LOCK_PACKAGE = re.compile(r'^\s*"[^"]+":\s*\["([^"]+)"(?:,\s*"([^"]*)")?', re.MULTILINE)
_ALLOWED_BUNFIG = {"install": {"minimumReleaseAge"}}


class StaticBuildError(AdapterError):
    """Dependency preparation or the sandboxed build failed."""


@dataclass(frozen=True)
class Toolchain:
    bun: Path
    node_bin: Path

    @classmethod
    def detect(cls) -> "Toolchain":
        bun, node = shutil.which("bun"), shutil.which("node")
        if bun is None or node is None:
            raise StaticBuildError("bun and node are required to build this source family")
        return cls(bun=Path(bun).resolve(), node_bin=Path(node).resolve().parent)


def _declared(package: dict) -> set[str]:
    return {
        name
        for section in ("dependencies", "devDependencies", "optionalDependencies")
        for name in package.get(section, {})
    }


def _lock_name(ident: str) -> str:
    return ident[: ident.index("@", 1)] if "@" in ident[1:] else ident


def validate_install_inputs(app: Path, *, stale_workspaces_allowed: bool = False) -> None:
    """Refuses anything that would make `bun install` fetch from somewhere
    other than the default registry, read credentials or run scripts.
    `stale_workspaces_allowed` (before install only): a `workspace:` lock
    entry is tolerated for a package package.json no longer declares — the
    cleanup removed it and bun prunes it; everything else stays strict."""
    if (app / ".npmrc").exists():
        raise StaticBuildError(".npmrc is not allowed in an exported source")
    bunfig = app / "bunfig.toml"
    if bunfig.exists():
        config = tomllib.loads(bunfig.read_text(encoding="utf-8"))
        for section, values in config.items():
            allowed = _ALLOWED_BUNFIG.get(section)
            if allowed is None or not isinstance(values, dict) or set(values) - allowed:
                raise StaticBuildError(f"bunfig.toml [{section}] contains settings outside the allowlist")
    package = json.loads((app / "package.json").read_text(encoding="utf-8"))
    if package.get("trustedDependencies"):
        raise StaticBuildError("trustedDependencies would let dependency install scripts run")
    for section in ("dependencies", "devDependencies", "optionalDependencies", "overrides"):
        for name, spec in package.get(section, {}).items():
            if not isinstance(spec, str) or _FORBIDDEN_SPEC.search(spec) or not _SEMVER_SPEC.match(spec):
                raise StaticBuildError(f"{section}.{name}: only plain registry version specs are allowed ({spec!r})")
    lock = app / "bun.lock"
    if lock.exists():
        declared = _declared(package)
        for match in _LOCK_PACKAGE.finditer(lock.read_text(encoding="utf-8")):
            ident, resolved = match.groups()
            if "@workspace:" in ident and stale_workspaces_allowed and _lock_name(ident) not in declared:
                continue
            if resolved or any(marker in ident for marker in ("@workspace:", "@git", "@file:", "@link:", "@http")):
                raise StaticBuildError(f"bun.lock entry {ident!r} is not a default-registry package")


def _install_env(toolchain: Toolchain, home: Path) -> dict[str, str]:
    """Built from scratch, never copied from os.environ."""
    return {
        "PATH": f"{toolchain.bun.parent}:{toolchain.node_bin}:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "BUN_INSTALL_CACHE_DIR": str(home / "bun-cache"),
        "NO_COLOR": "1",
        "DO_NOT_TRACK": "1",
        "LANG": "C.UTF-8",
    }


_LOCK_ENTRY = re.compile(r'^\s*"([^"]+)":\s*\["([^"]+)"(.*)$')
_LOCK_INTEGRITY = re.compile(r'"(sha\d+-[A-Za-z0-9+/=]+)"\],?\s*$')


def lock_entries(app: Path) -> dict[str, tuple[str, str | None]] | None:
    """bun.lock's resolved packages: key -> (name@version, integrity).
    `workspace:` entries are excluded (the plan's cleanup may prune them)."""
    lock = app / "bun.lock"
    if not lock.exists():
        return None
    text = lock.read_text(encoding="utf-8")
    start = text.find('"packages"')
    entries: dict[str, tuple[str, str | None]] = {}
    for line in (text[start:] if start >= 0 else "").splitlines():
        match = _LOCK_ENTRY.match(line)
        if match is None or "@workspace:" in match.group(2):
            continue
        integrity = _LOCK_INTEGRITY.search(match.group(3))
        entries[match.group(1)] = (match.group(2), integrity.group(1) if integrity else None)
    return entries


_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def planned_additions(app: Path, before: dict[str, tuple[str, str | None]]) -> dict[str, str]:
    """Direct dependencies package.json declares that the export's lockfile
    did not pin — the ones the reviewed plan added (e.g. self-hosted
    @fontsource packages). Only EXACT versions qualify."""
    package = json.loads((app / "package.json").read_text(encoding="utf-8"))
    return {
        name: spec
        for section in ("dependencies", "devDependencies", "optionalDependencies")
        for name, spec in package.get(section, {}).items()
        if name not in before and isinstance(spec, str) and _EXACT_VERSION.match(spec)
    }


def check_lock_only_pruned(before: dict[str, tuple[str, str | None]] | None, app: Path) -> None:
    """R5.1: the reviewed lockfile is authoritative. After install, every
    resolved package (name@version + integrity) must be one the export's
    own lockfile already pinned — install may PRUNE (packages the plan
    removed; bun then re-hoists, so a pinned version may move to another
    lock key), never upgrade or re-resolve. The only additions allowed are
    the plan's own direct dependencies at their exact pinned version."""
    if before is None:
        return
    pinned = set(before.values())
    allowed = {f"{name}@{version}" for name, version in planned_additions(app, before).items()}
    after = lock_entries(app) or {}
    changed = sorted(key for key, value in after.items() if value not in pinned and value[0] not in allowed)
    if changed:
        raise StaticBuildError(
            f"bun install changed the reviewed lockfile ({len(changed)} entries added or re-resolved, "
            f"e.g. {changed[:3]}) — refusing to build"
        )


def prepare_dependencies(app: Path, toolchain: Toolchain, *, frozen: bool, timeout: float | None = None) -> None:
    validate_install_inputs(app, stale_workspaces_allowed=not frozen)
    reviewed_lock = lock_entries(app)
    seconds = min(INSTALL_TIMEOUT_SECONDS, timeout) if timeout is not None else INSTALL_TIMEOUT_SECONDS
    if seconds <= 0:
        raise StaticBuildError("no time left for bun install before the job deadline")
    argv = [str(toolchain.bun), "install", "--ignore-scripts", *(["--frozen-lockfile"] if frozen else [])]
    with tempfile.TemporaryDirectory(prefix="gwa-bun-home-", dir=app.parent) as home:
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell
                argv,
                cwd=app,
                env=_install_env(toolchain, Path(home)),
                capture_output=True,
                text=True,
                timeout=seconds,
            )
        except subprocess.TimeoutExpired as exc:
            reason = "hit the job deadline" if seconds < INSTALL_TIMEOUT_SECONDS else "timed out"
            raise StaticBuildError(f"bun install {reason} after {int(seconds)}s") from exc
    if result.returncode != 0:
        raise StaticBuildError(f"bun install failed (exit {result.returncode}): {result.stderr[-2000:]}")
    # The lockfile bun just wrote is re-validated: a resolution may never
    # introduce a non-registry source, nor anything the export did not pin.
    validate_install_inputs(app)
    check_lock_only_pruned(reviewed_lock, app)


def sandbox_env(toolchain: Toolchain) -> dict[str, str]:
    return {
        "PATH": f"{_BUN_IN_SANDBOX}:{toolchain.node_bin}:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "NO_COLOR": "1",
        "DO_NOT_TRACK": "1",
        "CI": "1",
    }


def build_in_sandbox(
    app: Path,
    toolchain: Toolchain,
    runner: SandboxRunner,
    *,
    steps: tuple[tuple[str, tuple[str, ...]], ...],
    output_dir: str = "dist/client",
    limits: SandboxLimits = BUILD_LIMITS,
    deadline: float | None = None,
) -> Path:
    """Runs the adapter's build steps (H2: from its BuildSpec — the export's
    own install check and `bun run build`) in the R4 sandbox; returns the
    static output directory. `deadline` (time.monotonic()) bounds the whole
    sequence: each step gets at most the time left (R5.1 job deadline)."""
    binds = ((str(toolchain.bun.parent), _BUN_IN_SANDBOX),)
    env = sandbox_env(toolchain)
    for step, argv in steps:
        step_limits = limits
        if deadline is not None:
            left = int(deadline - time.monotonic())
            if left <= 0:
                raise StaticBuildError(f"no time left for {step} before the job deadline")
            step_limits = replace(limits, wall_timeout_seconds=min(limits.wall_timeout_seconds, left))
        runner.run(list(argv), workspace=app, env=env, limits=step_limits, step=step, ro_binds=binds)
    client = app / output_dir
    if not (client / "index.html").is_file():
        raise StaticBuildError(f"the build produced no static {output_dir}/index.html (prerender did not run)")
    return client
