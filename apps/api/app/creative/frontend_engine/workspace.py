"""Isolated per-generation workspace management (P2 "Workspace
Isolation") — every real security control the AI Frontend Engineer's
output passes through before a single byte reaches disk or a single
subprocess runs. Mirrors app.publishing.build's own scratch-directory
reasoning (same filesystem-device constraint for `astro build`'s asset
move step — see that module's `_BUILD_SCRATCH_DIR` docstring) but for an
ad-hoc, non-pnpm-workspace project rather than the shared site-builder
app, since a bespoke generative site isn't expressible as SiteConfig data
plugged into that app.

Threat model this module addresses directly (P2 Part K):
- workspace/path traversal: `_validate_relative_path` rejects absolute
  paths, `..` segments, and empty paths before any write.
- arbitrary file types: `ALLOWED_EXTENSIONS` rejects anything not a
  plain content file an Astro site legitimately needs.
- tampering with the trusted runtime: `RESERVED_PATHS` rejects any
  AI-submitted file at a path the engine itself owns (platform SDK,
  package.json, astro.config.mjs, tsconfig.json).
- server-side code the platform doesn't support: any path under
  `src/pages/api/` is rejected — a generated site must stay fully
  static and call the real backend through the platform SDK, never
  implement its own server endpoint.
- secret files: `.env`-shaped names are rejected outright.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

from app.creative.errors import CreativeProviderError
from app.creative.frontend_engine.manifest import GeneratedProjectManifest

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PLATFORM_SDK_RELATIVE_PATH = "src/lib/platform-sdk.ts"

ALLOWED_CONTENT_EXTENSIONS = frozenset({".astro", ".ts", ".tsx", ".css", ".json", ".svg", ".js"})
ALLOWED_CONTENT_ROOTS = ("src/", "public/")

RESERVED_PATHS = frozenset(
    {
        "package.json",
        "astro.config.mjs",
        "tsconfig.json",
        _PLATFORM_SDK_RELATIVE_PATH,
    }
)


class WorkspaceSecurityError(CreativeProviderError):
    """A GeneratedProjectManifest entry failed a workspace-safety check —
    the whole generation is refused (no partial write of a manifest this
    codebase can't fully trust)."""


def allocate_workspace() -> Path:
    """A fresh, empty, isolated directory under the system temp root —
    never inside the monorepo checkout (unlike
    app.publishing.build._BUILD_SCRATCH_DIR, this workspace runs its own
    `npm install`, and no untrusted install process should ever run with
    the real repository, its secrets, or its git history anywhere on its
    filesystem path)."""
    return Path(tempfile.mkdtemp(prefix="gwa-generative-"))


def cleanup_workspace(workspace: Path) -> None:
    shutil.rmtree(workspace, ignore_errors=True)


def _validate_relative_path(path: str) -> Path:
    if not path or path.startswith("/") or path.startswith("~"):
        raise WorkspaceSecurityError(f"Rejected file path {path!r}: must be a non-empty relative path.")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise WorkspaceSecurityError(f"Rejected file path {path!r}: absolute paths and '..' are not allowed.")
    if path in RESERVED_PATHS:
        raise WorkspaceSecurityError(
            f"Rejected file path {path!r}: this path is engine-owned and cannot be overwritten by generated content."
        )
    if not any(path.startswith(root) for root in ALLOWED_CONTENT_ROOTS):
        raise WorkspaceSecurityError(
            f"Rejected file path {path!r}: generated content may only live under {ALLOWED_CONTENT_ROOTS!r}."
        )
    if path.startswith("src/pages/api/"):
        raise WorkspaceSecurityError(
            f"Rejected file path {path!r}: generated sites must stay fully static — no server endpoints "
            "of their own. Use the platform SDK to call the real backend instead."
        )
    if candidate.suffix.lower() not in ALLOWED_CONTENT_EXTENSIONS:
        raise WorkspaceSecurityError(
            f"Rejected file path {path!r}: extension {candidate.suffix!r} is not in the allowed set "
            f"{sorted(ALLOWED_CONTENT_EXTENSIONS)!r}."
        )
    if candidate.name.startswith("."):
        raise WorkspaceSecurityError(f"Rejected file path {path!r}: dotfiles are not allowed.")
    return candidate


def write_manifest(
    workspace: Path, manifest: GeneratedProjectManifest, *, package_json: dict, astro_config: str, tsconfig: str
) -> None:
    """The one place AI-submitted content ever touches disk. Every file
    path is validated (`_validate_relative_path`) *before* any file is
    written — a single invalid entry fails the whole manifest, nothing
    partial is left on disk. The three engine-authored config files and
    the platform SDK are written after, from parameters this function
    controls, never from the manifest — see this module's own docstring.
    """
    workspace_root = workspace.resolve()

    validated: list[tuple[Path, str]] = []
    for file in manifest.files:
        relative = _validate_relative_path(file.path)
        resolved = (workspace_root / relative).resolve()
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise WorkspaceSecurityError(
                f"Rejected file path {file.path!r}: resolves outside the workspace."
            ) from exc
        validated.append((resolved, file.content))

    for resolved, content in validated:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    import json as _json

    (workspace_root / "package.json").write_text(_json.dumps(package_json, indent=2), encoding="utf-8")
    (workspace_root / "astro.config.mjs").write_text(astro_config, encoding="utf-8")
    (workspace_root / "tsconfig.json").write_text(tsconfig, encoding="utf-8")

    sdk_path = workspace_root / _PLATFORM_SDK_RELATIVE_PATH
    sdk_path.parent.mkdir(parents=True, exist_ok=True)
    sdk_path.write_text((_TEMPLATES_DIR / "platform_sdk.ts").read_text(encoding="utf-8"), encoding="utf-8")


def workspace_key_for(workspace: Path) -> str:
    """A stable, opaque identifier for a workspace — recorded on
    GenerativeWebsiteArtifact.workspace_key for reproducibility/debugging
    (see that model's own docstring: the directory itself is transient
    and cleaned up after a successful build, this is a trail, not a
    promise the path still exists)."""
    return f"{workspace.name}-{uuid.uuid5(uuid.NAMESPACE_URL, str(workspace))}"
