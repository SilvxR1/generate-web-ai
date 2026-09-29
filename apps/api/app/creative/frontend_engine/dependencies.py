"""v0.2 R4.2 — trusted dependency preparation for the execution host.

    trusted: npm ci --ignore-scripts (vetted lockfile, once per lockfile)
        -> read-only node_modules
        -> mounted into every networkless build (sandbox.py)

The dependency set is engine-owned and identical for every job (generated
code can add no dependency — S0), so it is installed once, by trusted code,
into `<root>/<lockfile sha256>/node_modules`, then made read-only. Jobs
never install anything and never need the registry; generated code can
neither run a lifecycle script nor alter the dependencies the next job uses.
"""

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from app.creative.frontend_engine.templates import build_package_json, vetted_lockfile
from app.publishing.errors import WebsitePublisherError

logger = logging.getLogger(__name__)

_MARKER = ".gwa-prepared"
_INSTALL_TIMEOUT_SECONDS = 600
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class DependencyPreparationError(WebsitePublisherError):
    """Prepared dependencies are missing, stale or could not be installed."""


def lockfile_digest() -> str:
    return hashlib.sha256(vetted_lockfile().encode("utf-8")).hexdigest()


def verify_prepared_dependencies(prepared: Path) -> Path:
    """The node_modules to mount, only if it was prepared from THIS
    lockfile (fail closed on a missing or stale preparation)."""
    marker = prepared / _MARKER
    node_modules = prepared / "node_modules"
    if prepared.is_symlink() or node_modules.is_symlink() or not node_modules.is_dir() or not marker.is_file():
        raise DependencyPreparationError("prepared dependencies are missing")
    if marker.read_text(encoding="utf-8").strip() != lockfile_digest():
        raise DependencyPreparationError("prepared dependencies do not match the vetted lockfile")
    return node_modules


def _set_writable(root: Path, writable: bool) -> None:
    paths = [root]
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        paths += [Path(dirpath) / name for name in [*dirnames, *filenames]]
    for path in paths:
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        path.chmod(mode | stat.S_IWUSR if writable else mode & ~_WRITE_BITS)


def _remove(path: Path) -> None:
    _set_writable(path, True)
    shutil.rmtree(path, ignore_errors=True)


def remove_prepared_dependencies(root: Path) -> None:
    """Deletes a preparation root (its trees are read-only by design)."""
    if root.exists():
        _remove(root)


def prepare_dependencies(root: Path) -> Path:
    """Idempotent: returns `<root>/<digest>` once it holds a verified,
    read-only install of the vetted lockfile, installing it if needed."""
    from app.creative.frontend_engine.build import generative_build_env  # avoids an import cycle

    digest = lockfile_digest()
    target = root / digest
    try:
        verify_prepared_dependencies(target)
        return target
    except DependencyPreparationError:
        pass

    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    toolchain = Path(tempfile.mkdtemp(prefix="gwa-toolchain-"))
    try:
        package = build_package_json(name="gwa-prepared-dependencies", additional_dependencies=[])
        (staging / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")
        (staging / "package-lock.json").write_text(vetted_lockfile(), encoding="utf-8")
        logger.info("preparing generative build dependencies (lockfile %s)", digest[:12])
        result = subprocess.run(  # noqa: S603 — fixed argv, clean env, no generated input
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=staging,
            env=generative_build_env(toolchain),
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise DependencyPreparationError(f"dependency preparation failed (exit {result.returncode})")
        (staging / _MARKER).write_text(digest, encoding="utf-8")
        _set_writable(staging, False)
        if target.exists():
            _remove(target)
        staging.rename(target)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencyPreparationError(f"dependency preparation failed: {type(exc).__name__}") from exc
    finally:
        shutil.rmtree(toolchain, ignore_errors=True)
        if staging.exists():
            _remove(staging)
    return target
