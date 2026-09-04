"""SiteConfigPayload -> a real, production Astro build — the same
BusinessConfig -> generateSiteConfig() -> @generate-web-ai/renderer /
@generate-web-ai/blocks / Tailwind pipeline apps/clients/* use, just
parameterized by data (apps/site-builder) instead of hand-authored per
client. No second renderer, no duplicated blocks: this module's only job
is invoking the real `astro build` as a subprocess and reading back
whatever it wrote, as a WebsiteArtifact (app.publishing.publisher).

Deliberately synchronous, in-process, no queue: one `astro build`
subprocess per publish request, same shape as every other engine call in
this codebase (n8n, the hosting provider itself) — see this phase's
"no queue/Redis salvo que sea imprescindible" scope.
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import WebsiteArtifact
from app.schemas.site_config import SiteConfigPayload

def _find_repo_root(start: Path) -> Path:
    """Walks up from `start` looking for pnpm-workspace.yaml — the one
    file that only ever exists at the monorepo root — instead of a fixed
    `parents[N]` index. A fixed index silently pointed at the wrong
    directory (or raised IndexError) the moment this file's depth
    relative to the repo root changed, which is exactly what happens
    once this runs inside a container: e.g. Railway building with the
    monorepo root as build context but an extra `WORKDIR` layer, or any
    other layout that isn't this exact host checkout's directory depth.
    """
    for candidate in (start, *start.parents):
        if (candidate / "pnpm-workspace.yaml").is_file():
            return candidate
    raise RuntimeError(
        f"could not find the generate-web-ai monorepo root (no pnpm-workspace.yaml found above {start}) "
        "— app.publishing.build needs a full monorepo checkout, not apps/api on its own."
    )


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
SITE_BUILDER_DIR = _REPO_ROOT / "apps" / "site-builder"

# `astro build`'s internal asset-move step uses a plain filesystem
# rename from its own .astro/ cache dir to --outDir; that fails with
# EXDEV if --outDir lands on a different filesystem/device (e.g. a
# system temp dir on tmpfs while the repo lives on the main disk) — so
# every build's scratch directory lives under the site-builder app
# itself, not /tmp, guaranteeing the same device.
_BUILD_SCRATCH_DIR = SITE_BUILDER_DIR / ".tmp-builds"

_BUILD_TIMEOUT_SECONDS = 120


class SiteBuildError(WebsitePublisherError):
    """The `astro build` subprocess failed (missing pnpm, a bad
    SiteConfig the renderer/blocks reject, a build timeout, ...). Treated
    exactly like any other WebsitePublisherError by
    app.publishing.service: the publish attempt fails, nothing is
    reported live."""


def build_site(site_config: SiteConfigPayload) -> WebsiteArtifact:
    if not SITE_BUILDER_DIR.is_dir():
        raise SiteBuildError(
            f"apps/site-builder is missing at {SITE_BUILDER_DIR} — this backend must run "
            "alongside the generate-web-ai monorepo checkout to build real websites."
        )

    build_id = uuid.uuid4().hex
    scratch_dir = _BUILD_SCRATCH_DIR / build_id
    out_dir = scratch_dir / "dist"
    config_path = scratch_dir / "site-config.json"

    try:
        scratch_dir.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(site_config.model_dump(mode="json")), encoding="utf-8")

        result = subprocess.run(
            ["pnpm", "exec", "astro", "build", "--outDir", str(out_dir)],
            cwd=SITE_BUILDER_DIR,
            env={**_subprocess_env(), "SITE_CONFIG_PATH": str(config_path)},
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise SiteBuildError(f"astro build failed (exit {result.returncode}): {_tail(result.stderr)}")

        return _read_artifact(out_dir)
    except subprocess.TimeoutExpired as exc:
        raise SiteBuildError(f"astro build timed out after {_BUILD_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise SiteBuildError(f"could not run astro build: {exc}") from exc
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def _subprocess_env() -> dict[str, str]:
    # No secrets flow through this build (SiteConfig content only) —
    # inheriting the parent environment is safe; still explicit here
    # (not `env=None`) so SITE_CONFIG_PATH is guaranteed to win over
    # anything stray already set.
    return dict(os.environ)


def _read_artifact(out_dir: Path) -> WebsiteArtifact:
    if not out_dir.is_dir():
        raise SiteBuildError(f"astro build reported success but {out_dir} doesn't exist")

    files: dict[str, bytes] = {}
    for path in out_dir.rglob("*"):
        if path.is_file():
            relative = path.relative_to(out_dir).as_posix()
            files[relative] = path.read_bytes()

    if "index.html" not in files:
        raise SiteBuildError("astro build produced no index.html")

    return WebsiteArtifact(files=files, entry_point="index.html")


def _tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else f"…{text[-limit:]}"
