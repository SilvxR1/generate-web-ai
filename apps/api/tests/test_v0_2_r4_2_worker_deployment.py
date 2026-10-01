"""v0.2 R4.2 — production sandbox worker deployment (local/CI evidence).

What the real worker VM must also prove (scripts/r4_host_acceptance.py runs
this file together with the R4 and R4.1 suites):

- trusted, read-only prepared dependencies (no per-job install, generated
  code cannot alter them) and fail-closed on stale preparation;
- CPU time and process count bounded; workspaces removed after failure and
  timeout, not only success;
- failure/restart semantics: lost workers fail job AND draft, results are
  accepted exactly once, expired/foreign tokens are refused, one job at a
  time;
- the worker process: systemd credential, https-only control plane, no
  crash when the control plane is down, bounded result retries, no secrets
  in logs;
- the deterministic infrastructure E2E (fixture job -> isolated build ->
  sandboxed Visual QA -> trusted intake -> READY), locally.

Host-capability checks skip on a non-production host but FAIL under
GWA_ACCEPTANCE=1 (the acceptance run). No provider, no production, no
external network.
"""

import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.creative import generation_jobs as jobs
from app.creative.frontend_engine import build as generative_build
from app.creative.frontend_engine.build import GenerativeBuildError, build_generative_workspace
from app.creative.frontend_engine.dependencies import (
    DependencyPreparationError,
    prepare_dependencies,
    remove_prepared_dependencies,
    verify_prepared_dependencies,
)
from app.creative.frontend_engine.sandbox import SandboxError, SandboxLimits, detect_runner
from app.creative.frontend_engine.templates import build_package_json, vetted_lockfile
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace
from app.db.models.website_draft import WebsiteDraft
from app.domain.enums import GenerationEngine, GenerationFailureKind, GenerationJobStatus, WebsiteDraftStatus
from app.repositories.generative_website_artifact import GenerativeWebsiteArtifactRepository
from app.storage import LocalStorageProvider
from app.storage.private import PrivateArtifactStorage
from app.worker import __main__ as worker_main
from app.worker import fixture_job, intake
from app.worker.auth import hash_worker_token, issue_job_token
from app.worker.executor import execute
from app.worker.protocol import ExecutionRequest, ExecutionResult, b64, pack_files, sha256_hex
from tests import test_v0_2_r2_feature_parity as _r2
from tests import test_v0_2_r4_1_execution_host as _r41

api = _r41.api  # the real app with an in-memory DB and temp storage

ACCEPTANCE = os.environ.get("GWA_ACCEPTANCE") == "1"
API_ROOT = Path(__file__).resolve().parents[1]
_NODE_DIR = str(Path(shutil.which("node") or "/usr/bin/node").resolve().parent)
_NODE_ENV = {"PATH": f"{_NODE_DIR}:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp", "LANG": "C.UTF-8"}


def _require(enforced: bool, what: str) -> None:
    if not enforced:
        if ACCEPTANCE:
            pytest.fail(f"{what} is not enforced on this host")
        pytest.skip(f"{what} is not enforced on this non-production host")


@pytest.fixture(scope="module")
def runner():
    return detect_runner()


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("deps")
    try:
        yield prepare_dependencies(root)
    finally:
        remove_prepared_dependencies(root)  # read-only by design; pytest alone cannot delete it


@pytest.fixture()
def ws():
    workspace = allocate_workspace()
    try:
        yield workspace
    finally:
        cleanup_workspace(workspace)


def _workspaces() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("gwa-*")}


def _request(source: dict[str, bytes], **extra) -> ExecutionRequest:
    archive = pack_files(source)
    return ExecutionRequest(
        job_id=uuid.uuid4(),
        attempt=1,
        business_id=uuid.uuid4(),
        api_base_url=_r2.API,
        source_archive=b64(archive),
        source_sha256=sha256_hex(archive),
        **extra,
    )


# --- Prepared dependencies ------------------------------------------------------------


def test_prepared_dependencies_are_read_only_to_generated_code(runner, prepared, ws):
    node_modules = verify_prepared_dependencies(prepared)
    (ws / "attack.js").write_text(
        "const fs=require('fs');const out={};"
        "for(const p of ['/workspace/node_modules/astro/package.json','/workspace/node_modules/evil.js']){"
        "try{fs.writeFileSync(p,'pwned');out[p]='WROTE'}catch(e){out[p]=e.code}}"
        "fs.writeFileSync('/workspace/result.json',JSON.stringify(out))"
    )
    runner.run(
        ["node", "attack.js"],
        workspace=ws,
        env=_NODE_ENV,
        limits=SandboxLimits(wall_timeout_seconds=30),
        step="attack",
        ro_binds=((str(node_modules), "/workspace/node_modules"),),
    )
    out = json.loads((ws / "result.json").read_text())
    assert set(out.values()) == {"EROFS"}, out
    assert not (node_modules / "evil.js").exists()
    assert b"pwned" not in (node_modules / "astro" / "package.json").read_bytes()


def test_stale_or_missing_prepared_dependencies_fail_closed(tmp_path, monkeypatch):
    with pytest.raises(DependencyPreparationError, match="missing"):
        verify_prepared_dependencies(tmp_path)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / ".gwa-prepared").write_text("0" * 64)
    with pytest.raises(DependencyPreparationError, match="do not match"):
        verify_prepared_dependencies(tmp_path)

    ran: list = []
    monkeypatch.setattr(generative_build.subprocess, "run", lambda *a, **k: ran.append(a))
    workspace = allocate_workspace()
    try:
        (workspace / "package.json").write_text(json.dumps(build_package_json(name="x", additional_dependencies=[])))
        (workspace / "package-lock.json").write_text(vetted_lockfile())
        with pytest.raises(GenerativeBuildError, match="do not match"):
            build_generative_workspace(workspace, business_id="b", prepared_dependencies=tmp_path)
    finally:
        cleanup_workspace(workspace)
    assert ran == []  # nothing installed, nothing built


# --- Resources ------------------------------------------------------------------------


def test_cpu_time_is_bounded(runner, ws):
    (ws / "spin.js").write_text("for(;;){}")
    started = time.monotonic()
    with pytest.raises(SandboxError) as excinfo:
        runner.run(
            ["node", "spin.js"],
            workspace=ws,
            env=_NODE_ENV,
            limits=SandboxLimits(wall_timeout_seconds=60, cpu_seconds=2),
            step="build",
        )
    assert "timed out" not in str(excinfo.value)  # killed by the CPU limit, not the wall clock
    assert time.monotonic() - started < 30


def test_process_count_is_capped_by_the_cgroup(runner, ws):
    _require(runner.limits_enforced()["process_count"], "the cgroup process-count limit")
    (ws / "spawn.js").write_text(
        "const cp=require('child_process');let ok=0,err=0;const kids=[];"
        "for(let i=0;i<150;i++){try{const c=cp.spawn('sleep',['5']);c.on('error',()=>err++);"
        "c.on('spawn',()=>ok++);kids.push(c)}catch(e){err++}}"
        "setTimeout(()=>{require('fs').writeFileSync('/workspace/count.json',JSON.stringify({ok,err}));"
        "kids.forEach(k=>{try{k.kill()}catch(e){}});process.exit(0)},2000)"
    )
    runner.run(
        ["node", "spawn.js"],
        workspace=ws,
        env=_NODE_ENV,
        limits=SandboxLimits(wall_timeout_seconds=60, max_processes=40),
        step="build",
    )
    counts = json.loads((ws / "count.json").read_text())
    assert counts["ok"] < 40 and counts["err"] > 0, counts


# --- Cleanup on failure and timeout -----------------------------------------------------


def test_workspaces_are_removed_after_a_failed_build(prepared):
    before = _workspaces()
    broken = {"src/pages/index.astro": b"---\nthis is ( not valid\n---\n<h1>x</h1>"}
    result = execute(_request(broken, run_visual_qa=False), prepared_dependencies=prepared)
    assert result.status == "failed" and result.failure_kind is GenerationFailureKind.BUILD
    assert _workspaces() <= before


def test_workspaces_are_removed_after_a_timed_out_build(prepared, monkeypatch):
    monkeypatch.setattr(generative_build, "_BUILD_LIMITS", SandboxLimits(wall_timeout_seconds=5))
    before = _workspaces()
    endless = {"src/pages/index.astro": b"---\nwhile (true) {}\n---\n<h1>x</h1>"}
    result = execute(_request(endless, run_visual_qa=False), prepared_dependencies=prepared)
    assert result.status == "failed" and result.failure_kind is GenerationFailureKind.RESOURCE_LIMIT
    assert _workspaces() <= before


# --- Failure / restart semantics -----------------------------------------------------------


@pytest.fixture()
def stores(tmp_path):
    return (
        PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private")),
        LocalStorageProvider(root_dir=tmp_path / "public"),
    )


@pytest.fixture()
def configured_business(session, business):
    business.config = _r2._business_config().model_dump(mode="json")
    session.flush()
    return business


def _draft(session, tenant, business) -> WebsiteDraft:
    draft = WebsiteDraft(
        tenant_id=tenant.id,
        business_id=business.id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.BUILDING,
    )
    session.add(draft)
    session.flush()
    return draft


def _queued(session, tenant, business, stores):
    draft = _draft(session, tenant, business)
    job = intake.enqueue_generative_build(
        session,
        draft=draft,
        source_files={"src/pages/index.astro": b"<h1>x</h1>"},
        idempotency_key=f"job-{uuid.uuid4()}",
        input_sha256="a" * 64,
        artifact_storage=stores[0],
        api_base_url=_r2.API,
    )
    session.flush()
    return draft, job


def test_a_lost_worker_fails_job_and_draft_and_is_never_retried(session, tenant, business, stores):
    draft, job = _queued(session, tenant, business, stores)
    claimed = intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k")
    assert claimed is not None and job.status is GenerationJobStatus.RUNNING
    assert intake.expire_lost(session) == 0  # lease still valid
    assert intake.expire_lost(session, now=datetime.now(UTC) + timedelta(hours=1)) == 1
    assert job.status is GenerationJobStatus.FAILED and job.failure_kind is GenerationFailureKind.WORKER_LOST
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED and draft.artifact_key is None
    assert intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k") is None


def test_only_one_job_is_claimed_at_a_time(session, tenant, business, stores):
    _, first = _queued(session, tenant, business, stores)
    _, second = _queued(session, tenant, business, stores)
    assert intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k")
    assert sorted([first.status.value, second.status.value]) == ["queued", "running"]


def _running_job(session, tenant, business, monkeypatch):
    key = "signing-" + uuid.uuid4().hex
    monkeypatch.setattr(settings, "generation_worker_token_sha256", "0" * 64)
    monkeypatch.setattr(settings, "generation_worker_signing_key", key)
    draft = _draft(session, tenant, business)
    job = jobs.submit_job(
        session,
        tenant_id=tenant.id,
        business_id=business.id,
        idempotency_key=f"job-{uuid.uuid4()}",
        input_sha256="a" * 64,
        draft_id=draft.id,
        source_key="unused",
        source_sha256="b" * 64,
    )
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    session.commit()
    return draft, job, key


def test_a_result_is_accepted_exactly_once(api, session, tenant, configured_business, monkeypatch):
    draft, job, key = _running_job(session, tenant, configured_business, monkeypatch)
    headers = {"Authorization": f"Bearer {issue_job_token(job_id=job.id, attempt=1, signing_key=key)}"}
    body = ExecutionResult(
        job_id=job.id, attempt=1, status="failed", failure_kind=GenerationFailureKind.BUILD, error="x"
    ).model_dump(mode="json")
    url = f"/internal/generation-worker/jobs/{job.id}/result"
    assert api.post(url, json=body, headers=headers).status_code == 204
    assert api.post(url, json=body, headers=headers).status_code == 409  # a replay changes nothing
    session.expire_all()
    assert session.get(WebsiteDraft, draft.id).status is WebsiteDraftStatus.BUILD_FAILED


def test_expired_or_foreign_job_tokens_are_refused(api, session, tenant, configured_business, monkeypatch):
    _, job, key = _running_job(session, tenant, configured_business, monkeypatch)
    body = ExecutionResult(job_id=job.id, attempt=1, status="failed").model_dump(mode="json")
    url = f"/internal/generation-worker/jobs/{job.id}/result"
    expired = issue_job_token(job_id=job.id, attempt=1, signing_key=key, now=datetime.now(UTC) - timedelta(hours=1))
    foreign = issue_job_token(job_id=uuid.uuid4(), attempt=1, signing_key=key)
    for token in (expired, foreign):
        assert api.post(url, json=body, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_the_claim_endpoint_expires_lost_jobs_before_claiming(api, session, tenant, configured_business, monkeypatch):
    draft, job, _ = _running_job(session, tenant, configured_business, monkeypatch)
    job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    session.commit()
    token = "worker-" + uuid.uuid4().hex
    monkeypatch.setattr(settings, "generation_worker_token_sha256", hash_worker_token(token))
    response = api.post("/internal/generation-worker/claim", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    session.expire_all()
    assert session.get(WebsiteDraft, draft.id).status is WebsiteDraftStatus.BUILD_FAILED


# --- Worker process ---------------------------------------------------------------------


def _mock_client(responses: list) -> tuple[httpx.Client, list]:
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item)

    return httpx.Client(base_url="https://api.example.com", transport=httpx.MockTransport(handler)), calls


@pytest.mark.parametrize(
    ("responses", "outcome", "call_count"),
    [
        ([500, 204], "accepted", 2),
        ([httpx.ConnectError("down"), 409], "already_final", 2),
        ([409], "rejected_conflict", 1),
        ([401], "rejected_401", 1),
        ([503] * 5, "gave_up", 5),
    ],
)
def test_result_submission_retries_only_transient_failures(monkeypatch, caplog, responses, outcome, call_count):
    monkeypatch.setattr(worker_main.time, "sleep", lambda s: None)
    client, calls = _mock_client(list(responses))
    request = _request({"src/pages/index.astro": b"x"})
    result = ExecutionResult(job_id=request.job_id, attempt=1, status="failed")
    secret = "job-token-" + uuid.uuid4().hex
    with caplog.at_level(logging.DEBUG):
        assert worker_main._submit_result(client, request=request, job_token=secret, result=result) == outcome
    assert len(calls) == call_count
    assert secret not in caplog.text


def test_the_worker_token_comes_from_the_systemd_credential(tmp_path, monkeypatch):
    monkeypatch.delenv("GWA_WORKER_TOKEN", raising=False)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    with pytest.raises(worker_main.WorkerConfigError):
        worker_main.load_worker_token()
    (tmp_path / "worker-token").write_text("tok-" + "a" * 20 + "\n")
    assert worker_main.load_worker_token() == "tok-" + "a" * 20


def test_the_worker_refuses_a_plain_http_control_plane(monkeypatch):
    monkeypatch.setenv("GWA_API_BASE_URL", "http://api.example.com")
    with pytest.raises(worker_main.WorkerConfigError, match="https"):
        worker_main._client("t")


def test_an_unavailable_control_plane_never_crashes_the_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "selftest", lambda: 0)
    monkeypatch.setattr(worker_main, "startup_preflight", lambda isolation: True)  # R5.1 (own tests)
    monkeypatch.setattr(worker_main.worker_preflight, "forbidden_environment", lambda environ=None: [])
    monkeypatch.setenv("GWA_WORKER_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setattr(worker_main, "prepare_dependencies", lambda root: tmp_path)
    monkeypatch.setenv("GWA_WORKER_TOKEN", "t")
    client, _ = _mock_client([httpx.ConnectError("down")])
    monkeypatch.setattr(worker_main, "_client", lambda token: client)
    assert worker_main.serve(once=True) == 1  # reported and handled; nothing claimed


def test_a_revoked_worker_credential_stops_the_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "selftest", lambda: 0)
    monkeypatch.setattr(worker_main, "startup_preflight", lambda isolation: True)  # R5.1 (own tests)
    monkeypatch.setattr(worker_main.worker_preflight, "forbidden_environment", lambda environ=None: [])
    monkeypatch.setenv("GWA_WORKER_WORK_ROOT", str(tmp_path / "work"))
    monkeypatch.setattr(worker_main, "prepare_dependencies", lambda root: tmp_path)
    monkeypatch.setenv("GWA_WORKER_TOKEN", "t")
    client, _ = _mock_client([401])
    monkeypatch.setattr(worker_main, "_client", lambda token: client)
    assert worker_main.serve(once=False) == worker_main.EX_CONFIG  # permanent: systemd must not restart


# --- BASIC / rollback never touch the worker ------------------------------------------------


@pytest.mark.parametrize("module", ["app/publishing/build.py", "app/publishing/versions.py"])
def test_basic_and_rollback_never_use_the_external_worker(module):
    assert "app.worker" not in (API_ROOT / module).read_text()


# --- Deterministic infrastructure E2E (local) -------------------------------------------


def test_the_fixture_job_reaches_ready_through_the_isolated_path(
    session, tenant, configured_business, stores, prepared
):
    draft, job_id = fixture_job.enqueue_fixture_job(
        session,
        tenant_id=tenant.id,
        business_id=configured_business.id,
        artifact_storage=stores[0],
        api_base_url=_r2.API,
    )
    claimed = intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k")
    assert claimed is not None and claimed[0].job_id == job_id
    result = execute(claimed[0], prepared_dependencies=prepared)
    assert result.status == "succeeded", result.error
    job = jobs.get_job(session, tenant_id=tenant.id, job_id=job_id)
    assert job is not None
    business_config, business_truth = intake.load_job_inputs(session, job)
    intake.accept_result(
        session,
        job=job,
        result=result,
        business_config=business_config,
        business_truth=business_truth,
        artifact_storage=stores[0],
        asset_storage=stores[1],
    )
    assert job.status is GenerationJobStatus.SUCCEEDED, (job.error, draft.build_error)
    assert draft.status is WebsiteDraftStatus.READY and draft.artifact_sha256
    row = GenerativeWebsiteArtifactRepository(session).get_for_draft(tenant.id, configured_business.id, draft.id)
    assert row is not None and row.visual_qa_state["findings"] and row.screenshot_keys
