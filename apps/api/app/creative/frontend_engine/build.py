"""build_generative_workspace — runs a real `npm install` + `astro build`
inside an isolated generative workspace (app.creative.frontend_engine.workspace)
and returns the same transient app.publishing.publisher.WebsiteArtifact
shape app.publishing.build.build_site returns for the deterministic
engine, so both engines' output feeds the identical downstream QA
(app.qa.platform_contract.validate_platform_contract) and publisher
(app.publishing.publisher.WebsitePublisher.publish) unchanged.

Uses plain `npm`, not `pnpm exec`: this workspace is deliberately outside
the monorepo's pnpm-workspace.yaml (see workspace.py's own docstring on
why an untrusted install must never run with the real repository
anywhere on its path) — `pnpm exec` would look for pnpm-workspace.yaml
up the tree and either fail or accidentally resolve packages from the
real repo, neither of which is desired here.

TRUST BOUNDARY (v0.2 S0 + R4). Generated website source is UNTRUSTED CODE,
and `astro build` EXECUTES it (component frontmatter and bundling of
generated TS/JS). Since R4 that step runs ONLY inside the untrusted build
zone (app.creative.frontend_engine.sandbox): no inherited environment, no
network, no filesystem beyond the job's workspace, its own PID namespace
and resource limits — and fails closed where the host cannot enforce it.
Its output is only a CANDIDATE (`collect_candidate_files`): read without
following links, bounded, then judged by trusted code (PlatformContract,
TruthContract, SHA-256, private storage) before anything reaches READY.

The trusted install step stays outside the build zone (it needs the
registry) but executes no generated code:

- Environment: deny by default. The subprocess gets ONLY
  `generative_build_env()` — never the API process's environment, so no
  platform credential (AI provider, Cloudflare, DATABASE_URL, R2, email,
  Higgsfield, n8n, ...) is inherited. HOME/TMPDIR/npm cache point at a
  throwaway toolchain directory, so no user-level `.npmrc` or credential
  file is read either.
- Dependencies: `npm ci --ignore-scripts` against the engine's vetted
  lockfile (templates.VETTED_LOCKFILE_PATH), after a strict
  package.json/lockfile consistency check. No fresh resolution, no
  dependency lifecycle scripts.
- Generated files may only live under src/ and public/ with allowlisted
  extensions (workspace.py), so no .npmrc, package.json or config of theirs
  is ever read by the install.

Whether PRODUCTION can host the build zone is unproven
(GENERATIVE_BUILD_NETWORK_ISOLATION_DEBT, see the R4 architecture section);
the whole path stays disabled in production by
`settings.generative_website_builds_enabled` (default False).
"""

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from app.creative.frontend_engine.sandbox import SandboxError, SandboxLimits, SandboxRunner, detect_runner
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json, vetted_lockfile
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsiteArtifact
from app.publishing.security_headers import generate_headers_file

logger = logging.getLogger(__name__)

_INSTALL_TIMEOUT_SECONDS = 180
_BUILD_LIMITS = SandboxLimits(wall_timeout_seconds=120)
# Candidate output bounds (R4): what trusted code agrees to read back.
MAX_CANDIDATE_FILES = 2000
MAX_CANDIDATE_FILE_BYTES = 25 * 1024**2
MAX_CANDIDATE_TOTAL_BYTES = 100 * 1024**2
# astro's own CLI entry, run by node directly — no npm inside the build zone.
_ASTRO_BUILD_ARGV = ["node", "node_modules/astro/bin/astro.mjs", "build"]
_HEAD_CLOSE_TAG = re.compile(r"</head>", re.IGNORECASE)
_BODY_CLOSE_TAG = re.compile(r"</body>", re.IGNORECASE)
# v0.2 R2: the platform-owned consent banner (same ids/hooks as the legacy
# CookieConsentBanner.astro), injected into every page AFTER the AI's files
# are compiled — generated code never implements consent behavior.
PLATFORM_CONSENT_FRAGMENT = (Path(__file__).parent / "templates" / "platform_consent.html").read_text(
    encoding="utf-8"
).strip()
_INLINE_SCRIPT_PATTERN = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)


class GenerativeBuildError(WebsitePublisherError):
    """`npm install`/`astro build` failed inside the isolated generative
    workspace — treated exactly like SiteBuildError
    (app.publishing.build) by every downstream caller: the generation
    attempt fails, nothing reaches READY, and this is never silently
    swallowed into a deterministic-looking success (P2.14)."""


# The ONLY variable names an untrusted generative build ever receives
# (v0.2 S0). Nothing here is read from the API's own environment except
# the location of the Node.js toolchain, which is not secret.
GENERATIVE_BUILD_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "npm_config_cache",
        "npm_config_userconfig",
        "npm_config_update_notifier",
        "npm_config_fund",
        "npm_config_audit",
        "ASTRO_TELEMETRY_DISABLED",
    }
)
_SYSTEM_PATH_DIRS = ("/usr/local/bin", "/usr/bin", "/bin")


def generative_build_env(toolchain_dir: Path) -> dict[str, str]:
    """Deny by default: a fresh environment built from scratch — never a
    filtered copy of os.environ — containing only
    GENERATIVE_BUILD_ENV_ALLOWLIST. PATH is the directory holding the
    `node`/`npm` this API would run plus standard system directories;
    HOME/TMPDIR/npm cache/userconfig all live in `toolchain_dir`, a
    throwaway directory outside the workspace and the repository."""
    node = shutil.which("node")
    if node is None:
        raise GenerativeBuildError("node is not available on this server.")
    path_dirs = [str(Path(node).resolve().parent), os.path.dirname(node), *_SYSTEM_PATH_DIRS]
    home = toolchain_dir / "home"
    tmp = toolchain_dir / "tmp"
    cache = toolchain_dir / "npm-cache"
    for directory in (home, tmp, cache):
        directory.mkdir(parents=True, exist_ok=True)
    userconfig = home / ".npmrc"
    userconfig.touch()
    env = {
        "PATH": os.pathsep.join(dict.fromkeys(path_dirs)),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "npm_config_cache": str(cache),
        "npm_config_userconfig": str(userconfig),
        "npm_config_update_notifier": "false",
        "npm_config_fund": "false",
        "npm_config_audit": "false",
        "ASTRO_TELEMETRY_DISABLED": "1",
    }
    if set(env) != GENERATIVE_BUILD_ENV_ALLOWLIST:
        raise GenerativeBuildError("Generative build environment does not match its allowlist.")
    return env


def _verify_lockfile(workspace: Path) -> None:
    """Fails closed unless the workspace carries the vetted lockfile AND
    package.json's dependency specs are exactly the lockfile's root specs
    — any drift is refused here, before any install runs (npm ci alone
    would accept a changed range the locked version still satisfies)."""
    lock_path = workspace / "package-lock.json"
    if not lock_path.is_file():
        raise GenerativeBuildError("Dependency lockfile is missing — refusing to resolve dependencies freshly.")
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        package = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
        root = lock["packages"][""]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise GenerativeBuildError("Dependency lockfile or package.json is unreadable.") from exc
    for field in ("dependencies", "devDependencies"):
        if (package.get(field) or {}) != (root.get(field) or {}):
            raise GenerativeBuildError(
                f"package.json {field} do not match the vetted lockfile — refusing to install (dependency drift)."
            )


def sandbox_build_env(env: dict[str, str]) -> dict[str, str]:
    """The same allowlisted keys, with every writable location pointing at
    the build zone's private /tmp (the host toolchain dir does not exist
    there)."""
    return {
        **env,
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "npm_config_cache": "/tmp/npm-cache",
        "npm_config_userconfig": "/tmp/.npmrc",
    }


def collect_candidate_files(out_dir: Path) -> dict[str, bytes]:
    """Reads the untrusted build output as a CANDIDATE: never follows a
    link (a planted `dist/x -> /etc/passwd` or `-> other job` would
    otherwise be read by the trusted process), accepts regular files only,
    and bounds count and size."""
    if out_dir.is_symlink() or not out_dir.is_dir():
        raise GenerativeBuildError("astro build produced no output directory")
    files: dict[str, bytes] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(out_dir, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise GenerativeBuildError("candidate output contains a symbolic link — rejected")
            if name in dirnames:
                continue
            if not stat.S_ISREG(mode):
                raise GenerativeBuildError("candidate output contains a non-regular file — rejected")
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                data = handle.read(MAX_CANDIDATE_FILE_BYTES + 1)
            if len(data) > MAX_CANDIDATE_FILE_BYTES:
                raise GenerativeBuildError("candidate output file exceeds the size limit")
            total += len(data)
            if total > MAX_CANDIDATE_TOTAL_BYTES or len(files) >= MAX_CANDIDATE_FILES:
                raise GenerativeBuildError("candidate output exceeds the artifact size/file-count limit")
            files[path.relative_to(out_dir).as_posix()] = data
    return files


def _run(args: list[str], *, cwd: Path, env: dict[str, str], timeout: int, step: str) -> None:
    """`env` is always generative_build_env(); it is never logged."""
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GenerativeBuildError(f"{step} timed out after {timeout}s") from exc
    except OSError as exc:
        raise GenerativeBuildError(f"could not run {step}: {exc}") from exc
    if result.returncode != 0:
        raise GenerativeBuildError(f"{step} failed (exit {result.returncode}): {_tail(result.stderr)}")


def _inject_platform_config(html: str, *, business_id: str, api_base_url: str | None) -> str:
    """Server-controlled tenant identity, injected into build output
    *after* the AI's own files are compiled — see
    templates/platform_sdk.ts's own docstring for why this, not anything
    the AI wrote, is what platform-sdk.ts actually reads. Never trusts
    the generated markup to have declared its own businessId."""
    config = json.dumps({"businessId": business_id, "apiBaseUrl": api_base_url})
    tag = f'<script type="application/json" id="platform-config">{config}</script></head>'
    if _HEAD_CLOSE_TAG.search(html):
        return _HEAD_CLOSE_TAG.sub(tag, html, count=1)
    return tag + html  # No <head> found (malformed AI output) — prepend rather than silently drop config.


def _inject_platform_consent(html: str) -> str:
    """v0.2 R2: consent is platform-owned. The banner and its behavior are
    engine-authored and injected post-build into every page; generated
    code may only theme it through `--gwa-consent-*` CSS custom properties
    and open it via `data-open-consent-preferences` (the legacy hook)."""
    if _BODY_CLOSE_TAG.search(html):
        return _BODY_CLOSE_TAG.sub(lambda _: PLATFORM_CONSENT_FRAGMENT + "</body>", html, count=1)
    return html + PLATFORM_CONSENT_FRAGMENT  # No </body> (malformed AI output) — append rather than drop it.


def inline_script_hashes(html_files: list[str]) -> frozenset[str]:
    """Same CSP `script-src 'sha256-...'` computation as
    app.publishing.build._inline_script_hashes, duplicated (not
    imported) since that's a private helper of a sibling module — kept
    tiny and self-contained here rather than reaching into another
    module's underscore-prefixed internals."""
    hashes: set[str] = set()
    for html in html_files:
        for match in _INLINE_SCRIPT_PATTERN.finditer(html):
            body = match.group(1)
            if not body.strip():
                continue
            digest = hashlib.sha256(body.encode("utf-8")).digest()
            hashes.add(base64.b64encode(digest).decode("ascii"))
    return frozenset(hashes)


def rebuild_from_archive(archive: bytes, *, business_id: str, api_base_url: str | None = None) -> WebsiteArtifact:
    """Re-runs a real `npm install` + `astro build` from a previously
    archived generative source tar.gz (see
    app.creative.frontend_engine.anthropic_engine._archive_source) —
    never re-invokes the LLM. A8.3.4.1: no longer used to publish (a
    GENERATIVE draft now promotes its stored build output, see
    app.publishing.drafts) — only Visual QA of legacy drafts that
    predate stored artifacts still rebuilds from source here."""
    import tarfile
    from io import BytesIO

    workspace = allocate_workspace()
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
            tar.extractall(workspace, filter="data")  # noqa: S202 — trusted, platform-archived content, not user input
        # v0.2 S0: engine-owned scaffolding is always re-authored, never
        # taken from the archive (older archives predate the vetted
        # lockfile and carry their own package.json).
        (workspace / "package.json").write_text(
            json.dumps(build_package_json(name="gwa-generated-site", additional_dependencies=[]), indent=2),
            encoding="utf-8",
        )
        (workspace / "package-lock.json").write_text(vetted_lockfile(), encoding="utf-8")
        (workspace / "astro.config.mjs").write_text(ASTRO_CONFIG, encoding="utf-8")
        (workspace / "tsconfig.json").write_text(TSCONFIG, encoding="utf-8")
        return build_generative_workspace(workspace, business_id=business_id, api_base_url=api_base_url)
    finally:
        cleanup_workspace(workspace)


def build_generative_workspace(
    workspace: Path,
    *,
    business_id: str,
    api_base_url: str | None = None,
    runner: SandboxRunner | None = None,
) -> WebsiteArtifact:
    if not (workspace / "package.json").is_file():
        raise GenerativeBuildError(f"{workspace} has no package.json — write_manifest must run before building.")
    _verify_lockfile(workspace)
    try:
        runner = runner or detect_runner()  # fail closed BEFORE installing anything
    except SandboxError as exc:
        raise GenerativeBuildError(str(exc)) from exc

    toolchain_dir = Path(tempfile.mkdtemp(prefix="gwa-toolchain-"))
    try:
        env = generative_build_env(toolchain_dir)
        logger.info("frontend_engine npm ci started")
        _run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=workspace,
            env=env,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            step="npm ci",
        )
        logger.info("frontend_engine npm ci completed")
        logger.info("frontend_engine astro build started (sandbox=%s)", runner.name)
        try:
            runner.run(
                _ASTRO_BUILD_ARGV,
                workspace=workspace,
                env=sandbox_build_env(env),
                limits=_BUILD_LIMITS,
                step="astro build",
            )
        except SandboxError as exc:
            raise GenerativeBuildError(str(exc)) from exc
        logger.info("frontend_engine astro build completed")
    finally:
        shutil.rmtree(toolchain_dir, ignore_errors=True)

    files: dict[str, bytes] = {}
    html_texts: list[str] = []
    for relative, data in collect_candidate_files(workspace / "dist").items():
        if relative.endswith(".html"):
            html = data.decode("utf-8", errors="ignore")
            injected = _inject_platform_consent(
                _inject_platform_config(html, business_id=business_id, api_base_url=api_base_url)
            )
            html_texts.append(injected)
            files[relative] = injected.encode("utf-8")
        else:
            files[relative] = data

    if "index.html" not in files:
        raise GenerativeBuildError("astro build produced no index.html")

    # The same api_base_url injected into every page's platform-config
    # above, so connect-src allows exactly what the SDK calls (A8.3.4-P0.2).
    files["_headers"] = generate_headers_file(
        script_hashes=inline_script_hashes(html_texts), public_api_origin=api_base_url
    )

    return WebsiteArtifact(files=files, entry_point="index.html")


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
