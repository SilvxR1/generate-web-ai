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
   (its postinstall check and its own `bun run build`).
"""

import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
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


def prepare_dependencies(app: Path, toolchain: Toolchain, *, frozen: bool) -> None:
    validate_install_inputs(app, stale_workspaces_allowed=not frozen)
    argv = [str(toolchain.bun), "install", "--ignore-scripts", *(["--frozen-lockfile"] if frozen else [])]
    with tempfile.TemporaryDirectory(prefix="gwa-bun-home-") as home:
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell
                argv,
                cwd=app,
                env=_install_env(toolchain, Path(home)),
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise StaticBuildError(f"bun install timed out after {INSTALL_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise StaticBuildError(f"bun install failed (exit {result.returncode}): {result.stderr[-2000:]}")
    # The lockfile bun just wrote is re-validated: a resolution may never
    # introduce a non-registry source.
    validate_install_inputs(app)


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
    app: Path, toolchain: Toolchain, runner: SandboxRunner, *, limits: SandboxLimits = BUILD_LIMITS
) -> Path:
    """Runs the export's own install check and `bun run build` in the R4
    sandbox; returns the static client output directory."""
    binds = ((str(toolchain.bun.parent), _BUN_IN_SANDBOX),)
    env = sandbox_env(toolchain)
    steps = [("bun run build", ["bun", "run", "build"])]
    if (app / "scripts/verify-install.mjs").exists():
        steps.insert(0, ("postinstall check", ["node", "scripts/verify-install.mjs"]))
    for step, argv in steps:
        runner.run(argv, workspace=app, env=env, limits=limits, step=step, ro_binds=binds)
    client = app / "dist" / "client"
    if not (client / "index.html").is_file():
        raise StaticBuildError("the build produced no static dist/client/index.html (prerender did not run)")
    return client
