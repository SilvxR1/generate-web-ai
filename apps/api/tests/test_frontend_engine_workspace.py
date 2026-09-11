"""app.creative.frontend_engine.workspace / dependency_policy — the P2
workspace-isolation and dependency-allowlist security tests (Part K/L):
path traversal, absolute paths, reserved-path tampering, disallowed
extensions, server-endpoint rejection, and arbitrary-dependency
rejection must all be refused before any file is written or any install
is attempted."""

import pytest

from app.creative.frontend_engine.dependency_policy import (
    ALLOWED_ADDITIONAL_DEPENDENCIES,
    DependencyPolicyError,
    resolve_dependencies,
    validate_dependencies,
)
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import (
    WorkspaceSecurityError,
    allocate_workspace,
    cleanup_workspace,
    write_manifest,
)


def _write(files: list[GeneratedFile]) -> None:
    workspace = allocate_workspace()
    try:
        manifest = GeneratedProjectManifest(files=files)
        package_json = build_package_json(name="test-site", additional_dependencies=[])
        write_manifest(workspace, manifest, package_json=package_json, astro_config=ASTRO_CONFIG, tsconfig=TSCONFIG)
    finally:
        cleanup_workspace(workspace)


def test_valid_manifest_writes_cleanly():
    _write([GeneratedFile(path="src/pages/index.astro", content="<h1>hi</h1>")])


@pytest.mark.parametrize(
    "bad_path",
    [
        "../../etc/passwd",
        "src/../../../etc/passwd",
        "/etc/passwd",
        "~/secrets",
        "",
    ],
)
def test_path_traversal_and_absolute_paths_are_rejected(bad_path: str):
    with pytest.raises(WorkspaceSecurityError):
        _write([GeneratedFile(path=bad_path, content="x")])


@pytest.mark.parametrize("reserved", ["package.json", "astro.config.mjs", "tsconfig.json", "src/lib/platform-sdk.ts"])
def test_engine_owned_paths_cannot_be_overwritten(reserved: str):
    with pytest.raises(WorkspaceSecurityError):
        _write([GeneratedFile(path=reserved, content="malicious override")])


def test_files_outside_src_or_public_are_rejected():
    with pytest.raises(WorkspaceSecurityError):
        _write([GeneratedFile(path="scripts/evil.sh", content="#!/bin/sh\nrm -rf /")])


def test_server_endpoints_are_rejected():
    with pytest.raises(WorkspaceSecurityError):
        _write([GeneratedFile(path="src/pages/api/leads.ts", content="export const POST = () => {};")])


@pytest.mark.parametrize("bad_extension_path", ["src/pages/evil.sh", "src/pages/evil.py", "src/pages/.env"])
def test_disallowed_extensions_and_dotfiles_are_rejected(bad_extension_path: str):
    with pytest.raises(WorkspaceSecurityError):
        _write([GeneratedFile(path=bad_extension_path, content="x")])


def test_platform_sdk_and_config_files_are_always_present_after_write():
    workspace = allocate_workspace()
    try:
        manifest = GeneratedProjectManifest(
            files=[GeneratedFile(path="src/pages/index.astro", content="<h1>hi</h1>")]
        )
        package_json = build_package_json(name="test-site", additional_dependencies=[])
        write_manifest(workspace, manifest, package_json=package_json, astro_config=ASTRO_CONFIG, tsconfig=TSCONFIG)

        assert (workspace / "package.json").is_file()
        assert (workspace / "astro.config.mjs").is_file()
        assert (workspace / "tsconfig.json").is_file()
        assert (workspace / "src/lib/platform-sdk.ts").is_file()
        # The AI never authored the SDK — its real content is what was written.
        sdk_content = (workspace / "src/lib/platform-sdk.ts").read_text()
        assert "submitLead" in sdk_content
        assert "gwaConsent" in sdk_content
    finally:
        cleanup_workspace(workspace)


# --- dependency_policy ---------------------------------------------------


def test_allowed_dependency_is_accepted():
    [name] = list(ALLOWED_ADDITIONAL_DEPENDENCIES)
    validate_dependencies([name])  # does not raise


def test_arbitrary_dependency_is_rejected():
    with pytest.raises(DependencyPolicyError):
        validate_dependencies(["left-pad", "some-malicious-package"])


def test_resolve_dependencies_never_uses_a_manifest_supplied_version():
    [name] = list(ALLOWED_ADDITIONAL_DEPENDENCIES)
    resolved = resolve_dependencies([name])
    assert resolved[name] == ALLOWED_ADDITIONAL_DEPENDENCIES[name]


def test_package_json_rejects_arbitrary_dependency_end_to_end():
    """A GeneratedProjectManifest requesting an arbitrary package must
    never reach npm install — the whole generation is refused before any
    file is written."""
    with pytest.raises(DependencyPolicyError):
        build_package_json(name="test-site", additional_dependencies=["totally-arbitrary-package"])
