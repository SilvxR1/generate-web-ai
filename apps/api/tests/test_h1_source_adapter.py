"""H1 source adapter — the reusable pieces, on small synthetic exports (the
real Higgsfield ZIP is not in the repository; scripts/h1_higgsfield_adapter.py
runs the real one locally)."""

import json
import stat
import zipfile
from pathlib import Path

import pytest

from app.creative.source_adapter.cleanup import DesignCriticalDependencyError, portability_cleanup
from app.creative.source_adapter.preview import parse_headers_file, resolve_path
from app.creative.source_adapter.records import (
    AdapterError,
    ContentBinding,
    JsonFieldPatch,
    PatchMismatchError,
    SourcePatch,
    apply_binding,
    apply_json_field,
    apply_patch,
)
from app.creative.source_adapter.snapshot import UnsafeArchiveError, snapshot_export
from app.creative.source_adapter.static_artifact import assemble_static_artifact, page_url_path
from app.creative.source_adapter.static_build import StaticBuildError, validate_install_inputs
from app.publishing.security_headers import CspExtensions


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _export(root: Path, *, index_imports_private: bool = False) -> Path:
    package = {
        "name": "site",
        "workspaces": ["packages/*"],
        "dependencies": {"react": "^19.2.7", "@vendor/ui": "workspace:*"},
    }
    index_import = 'import { Button } from "@vendor/ui/button";\n' if index_imports_private else ""
    _write(
        root,
        {
            "package.json": json.dumps(package),
            "src/routes/__root.tsx": 'import appCss from "../styles.css?url";\nexport const Route = 1;\n',
            "src/routes/index.tsx": index_import
            + 'import { Hero } from "@/components/site/hero";\nexport default Hero;\n',
            "src/components/site/hero.tsx": "export function Hero() { return null; }\n",
            "src/routes/app.tsx": 'import { Shell } from "@/components/shell";\nexport default Shell;\n',
            "src/components/shell/index.ts": 'export { Shell } from "./shell";\n',
            "src/components/shell/shell.tsx": 'import { Card } from "@vendor/ui/card";\nexport const Shell = Card;\n',
            "src/components/shell/shell.css": '@source "./shell.tsx";\n.a { @apply q-card; }\n',
            "src/components/panel/panel.tsx": "export const Panel = 1;\n",
            "src/components/panel/panel.css": ".b { @apply q-panel; }\n",
            "src/styles.css": (
                '@import "tailwindcss";\n@source "../packages/ui/src";\n@import "@vendor/ui/tailwind.css";\n'
                '@import "./components/shell/shell.css";\n@import "./components/panel/panel.css";\n.site{}\n'
            ),
            "src/server.ts": "export default {};\n",
            "tests/ui.test.ts": 'import { x } from "@vendor/ui";\n',
        },
    )
    return root


# --- PortabilityCleanup ---------------------------------------------------------


def test_cleanup_removes_only_unreachable_code_that_needs_the_missing_package(tmp_path):
    app = _export(tmp_path)
    result = portability_cleanup(app)
    assert result.unavailable_packages == ["@vendor/ui"]
    assert result.removed_routes == ["src/routes/app.tsx"]
    removed = {c.path for c in result.changes if c.kind == "cleanup-remove"}
    assert removed == {
        "src/routes/app.tsx",
        "src/components/shell/index.ts",
        "src/components/shell/shell.tsx",
        "tests/ui.test.ts",
    }
    assert (app / "src/components/site/hero.tsx").exists()  # the public site is untouched
    assert (app / "src/components/panel/panel.tsx").exists()  # dead but not tainted: kept
    assert (app / "src/styles.css").read_text() == '@import "tailwindcss";\n.site{}\n'
    package = json.loads((app / "package.json").read_text())
    assert "@vendor/ui" not in package["dependencies"] and "workspaces" not in package


def test_cleanup_stops_when_the_public_site_needs_the_missing_package(tmp_path):
    app = _export(tmp_path, index_imports_private=True)
    with pytest.raises(DesignCriticalDependencyError):
        portability_cleanup(app)
    assert (app / "src/routes/app.tsx").exists()  # nothing was removed


# --- Traceable patches and bindings ----------------------------------------------


def test_patch_must_match_exactly_once(tmp_path):
    _write(tmp_path, {"a.tsx": "x = 1;\nx = 1;\n"})
    with pytest.raises(PatchMismatchError):
        apply_patch(tmp_path, SourcePatch("a.tsx", "x = 1;\n", "x = 2;\n", "test"))
    record = apply_patch(tmp_path, SourcePatch("a.tsx", "x = 1;\nx = 1;\n", "x = 2;\n", "test"))
    assert record.before_sha256 != record.after_sha256
    assert (tmp_path / "a.tsx").read_text() == "x = 2;\n"


def test_binding_replaces_the_literal_inside_its_fragment_only(tmp_path):
    _write(tmp_path, {"f.tsx": "<p>Nexo Reformas</p>\n<!-- Nexo Reformas -->\n"})
    record = apply_binding(
        tmp_path, ContentBinding("f.tsx", "<p>Nexo Reformas</p>", "Nexo Reformas", "identity.name"), "Nexo Obras"
    )
    assert (tmp_path / "f.tsx").read_text() == "<p>Nexo Obras</p>\n<!-- Nexo Reformas -->\n"
    assert record.visible == "'Nexo Reformas' -> 'Nexo Obras'"


@pytest.mark.parametrize("value", ['Nexo" onload="x', "{evil}", "<script>", "a\nb", "   "])
def test_binding_refuses_values_that_could_change_the_source_syntax(tmp_path, value):
    _write(tmp_path, {"f.tsx": "<p>Nexo Reformas</p>\n"})
    with pytest.raises(AdapterError):
        apply_binding(tmp_path, ContentBinding("f.tsx", "<p>Nexo Reformas</p>", "Nexo Reformas", "x"), value)


def test_json_field_patch_requires_the_expected_prefix(tmp_path):
    _write(tmp_path, {"m.json": '{"og_image_url": "https://cdn.vendor.example/acct/a.png", "og_title": "T"}'})
    patch = JsonFieldPatch("m.json", "og_image_url", "https://cdn.vendor.example/", None, "test")
    apply_json_field(tmp_path, patch)
    assert json.loads((tmp_path / "m.json").read_text()) == {"og_image_url": None, "og_title": "T"}
    with pytest.raises(PatchMismatchError):  # already null: the export changed, stop
        apply_json_field(tmp_path, patch)


# --- SourceInventory ----------------------------------------------------------------


def _zip(path: Path, entries: dict[str, bytes], *, symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    return path


def test_snapshot_hashes_every_file_and_is_read_only(tmp_path):
    source = _zip(
        tmp_path / "export.zip",
        {
            "site/app/package.json": b'{"dependencies": {"react": "^19"}, "scripts": {"build": "vite build"}}',
            "site/app/bun.lock": b"{}",
            "site/app/public/a.png": b"png",
        },
    )
    snapshot = snapshot_export(source, tmp_path / "original")
    assert snapshot.app_dir == "site/app" and snapshot.package_manager == "bun"
    assert snapshot.build_command == "vite build" and snapshot.framework == {"react": "^19"}
    assert [f.path for f in snapshot.assets] == ["site/app/public/a.png"]
    assert len(snapshot.zip_sha256) == 64 and len(snapshot.files) == 3
    assert not (tmp_path / "original/site/app/package.json").stat().st_mode & stat.S_IWUSR


@pytest.mark.parametrize("name", ["../escape.txt", "/abs.txt", "a/../../b.txt"])
def test_snapshot_refuses_path_traversal(tmp_path, name):
    source = _zip(tmp_path / "bad.zip", {name: b"x", "app/package.json": b"{}"})
    with pytest.raises(UnsafeArchiveError):
        snapshot_export(source, tmp_path / "original")


def test_snapshot_refuses_symlinks(tmp_path):
    source = _zip(tmp_path / "bad.zip", {"app/package.json": b"{}"}, symlink="app/link")
    with pytest.raises(UnsafeArchiveError):
        snapshot_export(source, tmp_path / "original")


# --- Install-input validation -------------------------------------------------------


def test_install_inputs_accept_plain_registry_specs(tmp_path):
    _write(
        tmp_path,
        {
            "package.json": json.dumps({"dependencies": {"react": "^19.2.7", "nitro": "3.0.260429-beta"}}),
            "bunfig.toml": "[install]\nminimumReleaseAge = 86400\n",
            "bun.lock": '{\n  "packages": {\n    "react": ["react@19.2.7", "", {}, "sha512-x"],\n  }\n}\n',
        },
    )
    validate_install_inputs(tmp_path)


@pytest.mark.parametrize(
    "files",
    [
        {"package.json": json.dumps({"dependencies": {"x": "github:evil/x"}})},
        {"package.json": json.dumps({"dependencies": {"x": "https://evil.example/x.tgz"}})},
        {"package.json": json.dumps({"dependencies": {"x": "file:../x"}})},
        {"package.json": json.dumps({"dependencies": {"x": "npm:other@1"}})},
        {"package.json": json.dumps({"dependencies": {}, "trustedDependencies": ["esbuild"]})},
        {"package.json": "{}", ".npmrc": "registry=https://evil.example\n"},
        {"package.json": "{}", "bunfig.toml": '[install]\nregistry = "https://evil.example"\n'},
        {
            "package.json": "{}",
            "bun.lock": '{\n  "packages": {\n    "x": ["x@1.0.0", "https://evil.example/x.tgz", {}, "sha512-x"],\n'
            "  }\n}\n",
        },
        {
            "package.json": json.dumps({"dependencies": {"@v/ui": "1.0.0"}}),
            "bun.lock": '{\n  "packages": {\n    "@v/ui": ["@v/ui@workspace:packages/ui"],\n  }\n}\n',
        },
    ],
)
def test_install_inputs_refuse_non_registry_sources_and_script_hooks(tmp_path, files):
    _write(tmp_path, files)
    with pytest.raises(StaticBuildError):
        validate_install_inputs(tmp_path, stale_workspaces_allowed=True)


def test_a_stale_workspace_lock_entry_is_tolerated_only_before_install(tmp_path):
    _write(
        tmp_path,
        {
            "package.json": json.dumps({"dependencies": {"react": "^19"}}),
            "bun.lock": '{\n  "packages": {\n    "@v/ui": ["@v/ui@workspace:packages/ui"],\n  }\n}\n',
        },
    )
    validate_install_inputs(tmp_path, stale_workspaces_allowed=True)
    with pytest.raises(StaticBuildError):
        validate_install_inputs(tmp_path)


# --- Static artifact assembly ----------------------------------------------------------


def test_static_artifact_gets_platform_runtime_robots_sitemap_and_headers(tmp_path):
    _write(
        tmp_path,
        {
            "index.html": "<html><head><title>T</title></head><body><script>boot()</script></body></html>",
            "privacy/index.html": "<html><head></head><body></body></html>",
            "robots.txt": "Disallow: /",  # a build's own copy is never trusted
            "_headers": "/*\n  Content-Security-Policy: script-src *\n",
            "assets/app.js": "x",
        },
    )
    artifact = assemble_static_artifact(
        tmp_path,
        business_id="b-1",
        api_base_url="https://api.example.com",
        site_origin="https://site.example",
        csp_extensions=CspExtensions(media_blob=True),
    )
    index = artifact.files["index.html"].decode()
    assert '<script type="application/json" id="platform-config">' in index
    assert 'id="gwa-consent-banner"' in index
    assert artifact.files["robots.txt"].decode().endswith("Sitemap: https://site.example/sitemap.xml\n")
    sitemap = artifact.files["sitemap.xml"].decode()
    assert "<loc>https://site.example/</loc>" in sitemap and "<loc>https://site.example/privacy</loc>" in sitemap
    headers = artifact.files["_headers"].decode()
    assert "script-src *" not in headers and "media-src 'self' blob:" in headers
    assert "connect-src 'self' https://api.example.com" in headers


def test_page_url_paths():
    assert page_url_path("index.html") == "/"
    assert page_url_path("privacy/index.html") == "/privacy"
    assert page_url_path("about.html") == "/about"


# --- Local preview ------------------------------------------------------------------------


def test_preview_applies_the_all_paths_headers_block_and_resolves_directories():
    headers = parse_headers_file(b"/*\n  Content-Security-Policy: default-src 'self'\n  X-Frame-Options: DENY\n")
    assert headers == [("Content-Security-Policy", "default-src 'self'"), ("X-Frame-Options", "DENY")]
    files = {"index.html": b"", "privacy/index.html": b"", "_headers": b""}
    assert resolve_path(files, "/") == "index.html"
    assert resolve_path(files, "/privacy") == "privacy/index.html"
    assert resolve_path(files, "/_headers") is None
    assert resolve_path(files, "/../etc/passwd") is None
