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
"""

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsiteArtifact
from app.publishing.security_headers import generate_headers_file

_INSTALL_TIMEOUT_SECONDS = 180
_BUILD_TIMEOUT_SECONDS = 120
_HEAD_CLOSE_TAG = re.compile(r"</head>", re.IGNORECASE)
_INLINE_SCRIPT_PATTERN = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL)


class GenerativeBuildError(WebsitePublisherError):
    """`npm install`/`astro build` failed inside the isolated generative
    workspace — treated exactly like SiteBuildError
    (app.publishing.build) by every downstream caller: the generation
    attempt fails, nothing reaches READY, and this is never silently
    swallowed into a deterministic-looking success (P2.14)."""


def _subprocess_env() -> dict[str, str]:
    """No secrets flow into this subprocess — see this module's own
    docstring: the workspace never contains the real repository or its
    .env files, so inheriting the parent's environment carries no
    ambient credential the build process could read off disk; the
    Anthropic/Higgsfield credentials this backend itself holds are never
    passed as environment variables to this subprocess either."""
    import os

    return dict(os.environ)


def _run(args: list[str], *, cwd: Path, timeout: int, step: str) -> None:
    try:
        result = subprocess.run(args, cwd=cwd, env=_subprocess_env(), capture_output=True, text=True, timeout=timeout)
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


def _inline_script_hashes(html_files: list[str]) -> frozenset[str]:
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
    never re-invokes the LLM. This is how a GENERATIVE draft is
    published (app.publishing.service.publish_generative_website): the
    same real source that was approved, rebuilt fresh, not a second AI
    generation that could produce different content."""
    import tarfile
    from io import BytesIO

    workspace = allocate_workspace()
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
            tar.extractall(workspace, filter="data")  # noqa: S202 — trusted, platform-archived content, not user input
        return build_generative_workspace(workspace, business_id=business_id, api_base_url=api_base_url)
    finally:
        cleanup_workspace(workspace)


def build_generative_workspace(
    workspace: Path, *, business_id: str, api_base_url: str | None = None
) -> WebsiteArtifact:
    if not (workspace / "package.json").is_file():
        raise GenerativeBuildError(f"{workspace} has no package.json — write_manifest must run before building.")

    _run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=workspace,
        timeout=_INSTALL_TIMEOUT_SECONDS,
        step="npm install",
    )
    out_dir = workspace / "dist"
    _run(["npm", "run", "build"], cwd=workspace, timeout=_BUILD_TIMEOUT_SECONDS, step="astro build")

    if not out_dir.is_dir():
        raise GenerativeBuildError(f"astro build reported success but {out_dir} doesn't exist")

    files: dict[str, bytes] = {}
    html_texts: list[str] = []
    for path in out_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(out_dir).as_posix()
        if relative.endswith(".html"):
            html = path.read_text(encoding="utf-8", errors="ignore")
            injected = _inject_platform_config(html, business_id=business_id, api_base_url=api_base_url)
            html_texts.append(injected)
            files[relative] = injected.encode("utf-8")
        else:
            files[relative] = path.read_bytes()

    if "index.html" not in files:
        raise GenerativeBuildError("astro build produced no index.html")

    files["_headers"] = generate_headers_file(script_hashes=_inline_script_hashes(html_texts))

    return WebsiteArtifact(files=files, entry_point="index.html")


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
