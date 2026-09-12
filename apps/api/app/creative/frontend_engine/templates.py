"""Engine-authored project scaffolding — package.json/astro.config.mjs/
tsconfig.json are never AI-authored (see workspace.py's RESERVED_PATHS
and its docstring for why: a config file is exactly where "unexpected
config capable of escaping the build sandbox" would live). Output mode
is always `static` (matching app.publishing.build's expectation of a
pure static `dist/`, and P2's "do not introduce a second hosting/runtime
architecture" instruction) and there is no server adapter of any kind.
"""

import json

from app.creative.frontend_engine.dependency_policy import (
    BASE_DEPENDENCIES,
    BASE_DEV_DEPENDENCIES,
    resolve_dependencies,
)

ASTRO_CONFIG = """import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
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
