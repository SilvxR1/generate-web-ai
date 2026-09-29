"""Engine-authored project scaffolding — package.json/astro.config.mjs/
tsconfig.json are never AI-authored (see workspace.py's RESERVED_PATHS
and its docstring for why: a config file is exactly where "unexpected
config capable of escaping the build sandbox" would live). Output mode
is always `static` (matching app.publishing.build's expectation of a
pure static `dist/`, and P2's "do not introduce a second hosting/runtime
architecture" instruction) and there is no server adapter of any kind.
"""

import json
from pathlib import Path

from app.creative.frontend_engine.dependency_policy import (
    BASE_DEPENDENCIES,
    BASE_DEV_DEPENDENCIES,
    resolve_dependencies,
)

# v0.2 S0: the ONE vetted npm lockfile every generative workspace installs
# from (`npm ci`). Generated with `npm install --package-lock-only` for
# exactly BASE_DEPENDENCIES/BASE_DEV_DEPENDENCIES; every entry resolves from
# the public npm registry with an integrity hash. Regenerate (and review)
# it whenever those dependencies change — build.py refuses to install when
# package.json and this lockfile disagree.
VETTED_LOCKFILE_PATH = Path(__file__).parent / "templates" / "package-lock.json"


def vetted_lockfile() -> str:
    return VETTED_LOCKFILE_PATH.read_text(encoding="utf-8")

ASTRO_CONFIG = """import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
  // v0.2 R4.2: caches live in the build zone's private /tmp, so
  // node_modules can be mounted read-only (prepared dependencies).
  cacheDir: "/tmp/gwa-astro-cache",
  vite: { cacheDir: "/tmp/gwa-vite-cache" },
});
"""

TSCONFIG = json.dumps(
    {
        "extends": "astro/tsconfigs/strict",
        "compilerOptions": {"strict": True},
    },
    indent=2,
)


def build_package_json(*, name: str, additional_dependencies: list[str]) -> dict:
    resolved_extra = resolve_dependencies(additional_dependencies)
    return {
        "name": name,
        "private": True,
        "type": "module",
        "version": "0.0.0",
        "scripts": {"build": "astro build"},
        "dependencies": {**BASE_DEPENDENCIES, **resolved_extra},
        "devDependencies": {**BASE_DEV_DEPENDENCIES},
    }
