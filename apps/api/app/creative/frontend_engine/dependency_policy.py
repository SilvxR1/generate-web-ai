"""Machine-enforced dependency allowlist (P2 "Dependency Policy") — the
AI Frontend Engineer may never cause an arbitrary npm package to be
installed. `additional_dependencies` on a GeneratedProjectManifest
(app.creative.frontend_engine.manifest) is checked against
ALLOWED_DEPENDENCIES here; anything else raises before any file is
written or any install is attempted. Package.json itself is always
engine-authored (see workspace.py's templates) with pinned versions for
the always-included base (astro, typescript) — an approved *name* here
only ever resolves to this module's own pinned version, never a version
the manifest supplied.
"""

from app.creative.errors import CreativeProviderError

# Base dependencies every generated workspace gets regardless of what the
# manifest requests — pinned to the same major versions already used
# elsewhere in this monorepo (apps/site-builder), so a generative build
# behaves the same way a deterministic one does.
BASE_DEPENDENCIES: dict[str, str] = {
    "astro": "^7.2.3",
}
BASE_DEV_DEPENDENCIES: dict[str, str] = {
    "typescript": "^6.0.3",
}

# The small, reviewed set of *additional* creative dependencies a
# manifest may request by name — start minimal (P2: "smallest useful
# set"); extend this dict (name -> pinned version), never accept a
# manifest-supplied version, when a real generation genuinely needs one.
ALLOWED_ADDITIONAL_DEPENDENCIES: dict[str, str] = {
    "sharp": "^0.35.4",
}


class DependencyPolicyError(CreativeProviderError):
    """A GeneratedProjectManifest requested a dependency outside
    ALLOWED_ADDITIONAL_DEPENDENCIES — the generation is refused before
    any file is written or any `npm install` runs."""


def validate_dependencies(additional_dependencies: list[str]) -> None:
    disallowed = [name for name in additional_dependencies if name not in ALLOWED_ADDITIONAL_DEPENDENCIES]
    if disallowed:
        raise DependencyPolicyError(
            f"Requested dependencies not on the allowlist: {disallowed!r}. "
            f"Allowed: {sorted(ALLOWED_ADDITIONAL_DEPENDENCIES)!r}."
        )


def resolve_dependencies(additional_dependencies: list[str]) -> dict[str, str]:
    """Validates, then maps each approved *name* to this module's own
    pinned version (never the manifest's own, since it doesn't supply
    one) — the only way a dependency version reaches package.json."""
    validate_dependencies(additional_dependencies)
    return {name: ALLOWED_ADDITIONAL_DEPENDENCIES[name] for name in additional_dependencies}
