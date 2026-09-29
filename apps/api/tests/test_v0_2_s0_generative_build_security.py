"""v0.2 S0 — SECURE GENERATIVE BUILD (containment).

Generated website source is untrusted code that `astro build` executes.
These tests prove, with FAKE sentinel values only (never real credentials):

- the generative build subprocess never inherits the API environment —
  only an explicit allowlist reaches it;
- installation is deterministic: `npm ci --ignore-scripts` against the
  vetted lockfile, and any lockfile absence or drift fails closed before
  anything runs;
- the generative path is OFF by default and a direct API request cannot
  bypass the gate, while the BASIC/legacy draft path keeps working.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.creative.frontend_engine import build as generative_build
from app.creative.frontend_engine.build import (
    GENERATIVE_BUILD_ENV_ALLOWLIST,
    GenerativeBuildError,
    _run,
    build_generative_workspace,
    generative_build_env,
)
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.sandbox import SandboxRunner
from app.creative.frontend_engine.templates import (
    ASTRO_CONFIG,
    TSCONFIG,
    VETTED_LOCKFILE_PATH,
    build_package_json,
)
from app.creative.frontend_engine.workspace import (
    WorkspaceSecurityError,
    allocate_workspace,
    cleanup_workspace,
    write_manifest,
)

# Representative platform-secret NAMES with fake sentinel values.
_SENTINELS = {
    "ANTHROPIC_API_KEY": "s0-sentinel-anthropic",
    "DATABASE_URL": "postgresql://s0-sentinel-user:s0-sentinel-pass@db.invalid/s0",
    "CLOUDFLARE_API_TOKEN": "s0-sentinel-cloudflare",
    "R2_ACCESS_KEY_ID": "s0-sentinel-r2-id",
    "R2_SECRET_ACCESS_KEY": "s0-sentinel-r2-secret",
    "R2_PRIVATE_SECRET_ACCESS_KEY": "s0-sentinel-r2-private",
    "RESEND_API_KEY": "s0-sentinel-resend",
    "SMTP_PASSWORD": "s0-sentinel-smtp",
    "HIGGSFIELD_API_KEY_SECRET": "s0-sentinel-higgsfield",
    "N8N_API_KEY": "s0-sentinel-n8n",
    "INTERNAL_AUTOMATION_TOKEN": "s0-sentinel-internal",
}


@pytest.fixture()
def parent_secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name, value in _SENTINELS.items():
        monkeypatch.setenv(name, value)
    return _SENTINELS


def _write(ws: Path, files: list[GeneratedFile]) -> None:
    write_manifest(
        ws,
        GeneratedProjectManifest(files=files),
        package_json=build_package_json(name="s0-test", additional_dependencies=[]),
        astro_config=ASTRO_CONFIG,
        tsconfig=TSCONFIG,
    )


@pytest.fixture()
def workspace():
    ws = allocate_workspace()
    _write(ws, [GeneratedFile(path="src/pages/index.astro", content="<p>x</p>")])
    try:
        yield ws
    finally:
        cleanup_workspace(ws)


class _RecordingRun(SandboxRunner):
    """Stands in for subprocess.run (the trusted install) AND the sandbox
    runner (the untrusted build, R4): records argv/env, fakes a dist/."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, args, *, cwd, env, capture_output, text, timeout):
        self.calls.append((list(args), dict(env)))
        return subprocess.CompletedProcess(args, 0, "", "")

    def run(self, argv, *, workspace, env, limits, step):
        self.calls.append((list(argv), dict(env)))
        dist = Path(workspace) / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<html><head></head><body>ok</body></html>")


@pytest.fixture()
def recorded(monkeypatch: pytest.MonkeyPatch) -> _RecordingRun:
    recorder = _RecordingRun()
    monkeypatch.setattr(generative_build.subprocess, "run", recorder)
    monkeypatch.setattr(generative_build, "detect_runner", lambda: recorder)
    return recorder


# --- 1. Environment: deny by default ----------------------------------------


def test_build_subprocesses_never_inherit_platform_secrets(parent_secrets, workspace, recorded):
    build_generative_workspace(workspace, business_id="b1", api_base_url="https://api.example.com")

    assert [call[0][:2] for call in recorded.calls] == [["npm", "ci"], ["node", "node_modules/astro/bin/astro.mjs"]]
    for _, env in recorded.calls:
        for name, value in parent_secrets.items():
            assert name not in env, name
            assert all(value not in v for v in env.values()), name


def test_only_allowlisted_variables_reach_the_build(parent_secrets, workspace, recorded, monkeypatch):
    monkeypatch.setenv("SOME_UNRELATED_APP_SETTING", "s0-sentinel-unrelated")
    build_generative_workspace(workspace, business_id="b1")

    for _, env in recorded.calls:
        assert set(env) == GENERATIVE_BUILD_ENV_ALLOWLIST
        # Never the real HOME: user-level credentials/.npmrc are not read.
        assert env["HOME"] != str(Path.home())


def test_build_env_is_built_from_scratch_not_filtered(tmp_path, parent_secrets):
    env = generative_build_env(tmp_path)
    assert set(env) == GENERATIVE_BUILD_ENV_ALLOWLIST
    assert not (set(env) & set(parent_secrets))
    assert Path(env["HOME"]).is_relative_to(tmp_path)
    assert Path(env["npm_config_cache"]).is_relative_to(tmp_path)
    assert Path(env["npm_config_userconfig"]).read_text() == ""


def test_a_real_child_process_sees_no_parent_secret_and_errors_cannot_dump_them(tmp_path, parent_secrets):
    """Runs a real child with the build env that prints its whole
    environment and fails: nothing secret can appear in the error that is
    persisted as draft.build_error."""
    env = generative_build_env(tmp_path)
    dump = "import os,sys; sys.stderr.write(repr(dict(os.environ))); sys.exit(3)"
    with pytest.raises(GenerativeBuildError) as exc:
        _run([sys.executable, "-c", dump], cwd=tmp_path, env=env, timeout=30, step="env probe")
    message = str(exc.value)
    for name, value in parent_secrets.items():
        assert name not in message and value not in message, name


# --- 3/4. Dependencies: vetted lockfile, npm ci, no lifecycle scripts -----------


def test_install_is_npm_ci_with_lifecycle_scripts_disabled(workspace, recorded):
    build_generative_workspace(workspace, business_id="b1")
    install_args = recorded.calls[0][0]
    assert install_args[:2] == ["npm", "ci"]
    assert "--ignore-scripts" in install_args
    assert "install" not in install_args


def test_missing_lockfile_fails_closed_before_anything_runs(workspace, recorded):
    (workspace / "package-lock.json").unlink()
    with pytest.raises(GenerativeBuildError, match="lockfile is missing"):
        build_generative_workspace(workspace, business_id="b1")
    assert recorded.calls == []


def test_dependency_drift_fails_closed_before_anything_runs(workspace, recorded):
    package = json.loads((workspace / "package.json").read_text())
    package["dependencies"]["left-pad"] = "^1.3.0"
    (workspace / "package.json").write_text(json.dumps(package))
    with pytest.raises(GenerativeBuildError, match="dependency drift"):
        build_generative_workspace(workspace, business_id="b1")
    assert recorded.calls == []

    package["dependencies"].pop("left-pad")
    package["dependencies"]["astro"] = "^7.0.0"  # a range the lock would still satisfy: refused too
    (workspace / "package.json").write_text(json.dumps(package))
    with pytest.raises(GenerativeBuildError, match="dependency drift"):
        build_generative_workspace(workspace, business_id="b1")
    assert recorded.calls == []


def test_vetted_lockfile_matches_the_engine_package_json_and_the_public_registry():
    lock = json.loads(VETTED_LOCKFILE_PATH.read_text())
    package = build_package_json(name="any", additional_dependencies=[])
    root = lock["packages"][""]
    assert root.get("dependencies") == package["dependencies"]
    assert root.get("devDependencies") == package["devDependencies"]
    for path, entry in lock["packages"].items():
        if not path or entry.get("link"):
            continue
        assert entry["resolved"].startswith("https://registry.npmjs.org/"), path
        assert entry["integrity"].startswith("sha512-"), path


def test_install_scripts_in_the_vetted_lockfile_are_known_and_never_run():
    """Documents which locked packages declare lifecycle scripts; with
    `--ignore-scripts` none of them execute (esbuild ships its binary via
    an optional platform package; fsevents is macOS-only)."""
    lock = json.loads(VETTED_LOCKFILE_PATH.read_text())
    with_scripts = sorted(path for path, entry in lock["packages"].items() if entry.get("hasInstallScript"))
    assert with_scripts == ["node_modules/esbuild", "node_modules/fsevents"]


def test_workspace_writes_the_vetted_lockfile_and_generated_content_cannot_replace_it(workspace):
    assert (workspace / "package-lock.json").read_text() == VETTED_LOCKFILE_PATH.read_text()
    with pytest.raises(WorkspaceSecurityError):
        _write(workspace, [GeneratedFile(path="package-lock.json", content="{}")])


# --- 8/9. Feature gate --------------------------------------------------------


def test_generative_builds_are_disabled_by_default():
    assert Settings.model_fields["generative_website_builds_enabled"].default is False
    assert settings.generative_website_builds_enabled is False  # never enabled implicitly


@pytest.fixture()
def api(session):
    from app.dependencies import get_frontend_engineer, get_session
    from app.main import app

    engineer_calls: list[str] = []

    def _engineer():
        engineer_calls.append("constructed")
        raise AssertionError("the frontend engineer must never be reached while disabled")

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_frontend_engineer] = _engineer
    client = TestClient(app)
    client.engineer_calls = engineer_calls  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_frontend_engineer, None)


def test_direct_api_requests_cannot_bypass_the_gate(api, tenant, business, session):
    from app.db.models.website_draft import WebsiteDraft

    headers = {"X-Tenant-Id": str(tenant.id)}
    base = f"/businesses/{business.id}"
    drafts_before = session.query(WebsiteDraft).count()

    create = api.post(
        f"{base}/website-drafts/generative",
        json={"creative_direction_id": "00000000-0000-0000-0000-000000000001"},
        headers=headers,
    )
    qa = api.post(f"{base}/website-drafts/00000000-0000-0000-0000-000000000002/visual-qa", headers=headers)

    for response in (create, qa):
        assert response.status_code == 403, response.text
        assert response.json() == {
            "error": {"code": "feature_not_available", "message": "This feature is not available."}
        }
        for word in ("ANTHROPIC", "secret", "environment", "sandbox"):
            assert word not in response.text
    assert api.engineer_calls == []
    assert session.query(WebsiteDraft).count() == drafts_before  # nothing created


def test_capability_reports_the_gate_to_studio(api, tenant, business):
    response = api.get(
        f"/businesses/{business.id}/generative-pipeline-capability", headers={"X-Tenant-Id": str(tenant.id)}
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


# --- 11. BASIC / legacy path unaffected ---------------------------------------


def test_basic_draft_creation_still_works_with_the_generative_gate_off(
    session, tenant, business, tmp_path, monkeypatch
):
    """The legacy block path builds through app.publishing.build (trusted
    monorepo code), not the untrusted generative builder, and is never
    gated by the S0 flag."""
    from app.dependencies import get_private_artifact_storage, get_session
    from app.main import app
    from app.storage import LocalStorageProvider
    from app.storage.private import PrivateArtifactStorage
    from tests.test_a8_real_draft_preview import _SITE_CONFIG, BuildCounter

    counter = BuildCounter()
    monkeypatch.setattr("app.publishing.drafts.build_site", counter)
    storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private"))

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_private_artifact_storage] = lambda: storage
    try:
        response = TestClient(app).post(
            f"/businesses/{business.id}/website-drafts",
            json={"site_config": _SITE_CONFIG},
            headers={"X-Tenant-Id": str(tenant.id)},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_private_artifact_storage, None)

    assert settings.generative_website_builds_enabled is False
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"
    assert counter.calls == 1
