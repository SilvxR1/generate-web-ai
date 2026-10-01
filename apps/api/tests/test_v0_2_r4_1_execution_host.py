"""v0.2 R4.1 — production sandbox host: provider-independent integration.

Proves, on THIS host (local/CI), the pieces an external execution host will
run and the control-plane side that judges its output:

- Visual QA runs generated JavaScript in Chromium inside the build zone and
  cannot reach the host's local services, the internet or metadata;
- the execution protocol (source in, candidate out) and the worker executor;
- trusted intake: the host's candidate is re-verified (SHA-256, archive
  shape), re-headered and judged by PlatformContract + TruthContract before
  READY — a malicious host cannot bypass any gate;
- narrow credentials and dormant-by-default internal endpoints.

Nothing here proves any production host; see the R4.1 acceptance procedure.
No provider, no production, no external network.
"""

import hashlib
import http.server
import io
import os
import subprocess
import sys
import tarfile
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import settings
from app.creative import generation_jobs as jobs
from app.creative.frontend_engine import sandbox as sandbox_module
from app.creative.frontend_engine.browser_qa import BrowserQAUnavailableError, run_browser_qa
from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.sandboxed_browser_qa import run_browser_qa_sandboxed
from app.db.models.website_draft import WebsiteDraft
from app.domain.enums import GenerationEngine, GenerationFailureKind, GenerationJobStatus, WebsiteDraftStatus
from app.publishing.artifact_store import artifact_sha256, unpack_artifact
from app.storage import LocalStorageProvider
from app.storage.private import PrivateArtifactStorage
from app.worker import __main__ as worker_main
from app.worker import intake
from app.worker.auth import (
    WorkerAuthError,
    hash_worker_token,
    issue_job_token,
    verify_job_token,
    verify_worker_token,
)
from app.worker.executor import execute
from app.worker.protocol import (
    ExecutionRequest,
    ExecutionResult,
    ProtocolError,
    b64,
    pack_files,
    sha256_hex,
    unb64,
    unpack_candidate,
    unpack_source,
)
from tests import test_v0_2_r2_feature_parity as _r2

API_ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "r4-1-sentinel-must-never-leak"
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
_DESKTOP = (("desktop", 1024, 768),)


# --- Visual QA network isolation -----------------------------------------------------


class _Recorder(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).hits.append(self.path)
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"leaked")

    def log_message(self, *args):
        pass


@pytest.fixture()
def host_service():
    """A service on the HOST's loopback — stands in for the API, a local
    database admin port or any internal service."""
    _Recorder.hits = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()


def _hostile_page(port: int) -> dict[str, bytes]:
    script = (
        "window.__r={};const t=(k,u)=>fetch(u).then(()=>window.__r[k]='REACHED').catch(()=>window.__r[k]='blocked');"
        f"t('local','http://127.0.0.1:{port}/steal');t('internet','http://1.1.1.1/');"
        "t('metadata','http://169.254.169.254/latest/meta-data/');"
    )
    html = f"<html><head><title>x</title></head><body><h1>Hi</h1><script>{script}</script></body></html>"
    return {"index.html": html.encode()}


def test_positive_control_unsandboxed_chromium_does_reach_host_services(host_service):
    """Proves the hostile page and listener detect a leak when there is no
    boundary — so the sandboxed tests below are meaningful."""
    run_browser_qa(_hostile_page(host_service), viewports=_DESKTOP, probe_script="window.__r")
    assert "/steal" in _Recorder.hits


def test_sandboxed_visual_qa_network_namespace_alone_denies_everything(host_service):
    """offline_assets=None: no request routing at all — only the network
    namespace stands between the generated JavaScript and the network."""
    result = run_browser_qa_sandboxed(
        _hostile_page(host_service), offline_assets=None, viewports=_DESKTOP, probe_script="window.__r"
    )
    assert _Recorder.hits == []
    assert result.probes and all(v == "blocked" for v in result.probes[0].values()), result.probes


def test_sandboxed_visual_qa_serves_only_the_businesss_own_assets(host_service):
    asset_url = "https://pub.example.r2.dev/business/photo.png"
    page = (
        f'<html><head><title>x</title></head><body><h1>Hi</h1><img src="{asset_url}" alt="p">'
        f'<img src="http://127.0.0.1:{host_service}/pixel.png" alt="q"></body></html>'
    )
    result = run_browser_qa_sandboxed(
        {"index.html": page.encode()}, offline_assets={asset_url: _TINY_PNG}, viewports=_DESKTOP
    )
    assert _Recorder.hits == []
    assert any(u.startswith("http://127.0.0.1:") for u in result.blocked_requests)
    broken = next(f for f in result.findings if f.check == "no_broken_images")
    assert asset_url not in broken.detail  # the supplied asset rendered; only the foreign one broke


def test_visual_qa_fails_closed_without_a_sandbox(monkeypatch):
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    with pytest.raises(BrowserQAUnavailableError, match="cannot run isolated"):
        run_browser_qa_sandboxed({"index.html": b"<html></html>"}, viewports=_DESKTOP)


# --- Protocol -------------------------------------------------------------------------


def _tar(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def _info(name: str, *, size: int = 0, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size, info.type, info.linkname = size, kind, link
    return info


@pytest.mark.parametrize(
    "members",
    [
        [(_info("index.html", kind=tarfile.SYMTYPE, link="/etc/passwd"), None)],
        [(_info("x", kind=tarfile.LNKTYPE, link="index.html"), None)],
        [(_info("../escape.html", size=1), b"x")],
        [(_info("/abs.html", size=1), b"x")],
        [(_info("dev", kind=tarfile.CHRTYPE), None)],
    ],
)
def test_candidate_archives_with_links_escapes_or_devices_are_rejected(members):
    archive = _tar(members)
    with pytest.raises(ProtocolError):
        unpack_candidate(archive, expected_sha256=sha256_hex(archive))


def test_candidate_integrity_is_verified_before_anything_is_read():
    archive = pack_files({"index.html": b"<html></html>"})
    with pytest.raises(ProtocolError, match="SHA-256"):
        unpack_candidate(archive, expected_sha256="0" * 64)
    assert unpack_candidate(archive, expected_sha256=sha256_hex(archive)) == {"index.html": b"<html></html>"}


def test_source_archives_never_carry_engine_scaffolding():
    for name in ("package.json", "package-lock.json", "astro.config.mjs", ".npmrc"):
        with pytest.raises(ProtocolError, match="outside src/"):
            unpack_source(pack_files({"src/pages/index.astro": b"x", name: b"{}"}))


def test_protocol_payloads_are_bounded():
    with pytest.raises(ProtocolError, match="size limit"):
        unb64("A" * 1000, limit=10)


# --- Credentials ----------------------------------------------------------------------


def test_worker_credential_is_verified_against_its_hash_only():
    token = "worker-" + uuid.uuid4().hex
    verify_worker_token(token, expected_sha256=hash_worker_token(token))
    for presented, expected in ((None, hash_worker_token(token)), ("wrong", hash_worker_token(token)), (token, None)):
        with pytest.raises(WorkerAuthError):
            verify_worker_token(presented, expected_sha256=expected)


def test_job_tokens_are_bound_to_one_job_one_attempt_and_expire():
    job_id, key = uuid.uuid4(), "signing-" + uuid.uuid4().hex
    token = issue_job_token(job_id=job_id, attempt=1, signing_key=key)
    verify_job_token(token, job_id=job_id, attempt=1, signing_key=key)
    bad = [
        {"token": token, "job_id": uuid.uuid4(), "attempt": 1, "signing_key": key},
        {"token": token, "job_id": job_id, "attempt": 2, "signing_key": key},
        {"token": token, "job_id": job_id, "attempt": 1, "signing_key": "other-key"},
        {"token": token[:-2] + "xx", "job_id": job_id, "attempt": 1, "signing_key": key},
        {"token": token, "job_id": job_id, "attempt": 1, "signing_key": key, "now": datetime.now(UTC) + timedelta(1)},
    ]
    for kwargs in bad:
        with pytest.raises(WorkerAuthError):
            verify_job_token(**kwargs)


# --- Executor + trusted intake (real sandboxed build and Visual QA) --------------------


def _source_files() -> dict[str, bytes]:
    truth = _r2._truth()
    files = {f.path: f.content.encode() for f in _r2.freeform_manifest(truth).files}
    files.update({path: content.encode() for path, content in build_legal_pages(truth).items()})
    return files


def _request(source: dict[str, bytes], *, job_id: uuid.UUID, business_id: uuid.UUID, **extra) -> ExecutionRequest:
    archive = pack_files(source)
    return ExecutionRequest(
        job_id=job_id,
        attempt=1,
        business_id=business_id,
        api_base_url=_r2.API,
        source_archive=b64(archive),
        source_sha256=sha256_hex(archive),
        **extra,
    )


@pytest.fixture(scope="module")
def executed() -> tuple[ExecutionRequest, ExecutionResult]:
    """One real execution of the free-form fixture: sandboxed build + sandboxed Visual QA."""
    request = _request(_source_files(), job_id=uuid.uuid4(), business_id=uuid.uuid4())
    return request, execute(request)


def _candidate(result: ExecutionResult) -> dict[str, bytes]:
    assert result.candidate_archive is not None and result.candidate_sha256 is not None
    return unpack_candidate(unb64(result.candidate_archive, limit=10**9), expected_sha256=result.candidate_sha256)


def test_the_executor_returns_a_candidate_and_visual_qa_from_the_sandbox(executed):
    _, result = executed
    assert result.status == "succeeded", result.error
    assert "index.html" in _candidate(result)
    assert result.visual_qa is not None and result.visual_qa.screenshots
    assert result.metadata["runner"] == "bubblewrap"


def _workspaces() -> set[str]:
    import tempfile

    return {p.name for p in Path(tempfile.gettempdir()).glob("gwa-*")}


def test_the_execution_hosts_own_credential_never_reaches_generated_code(monkeypatch):
    monkeypatch.setenv("GWA_WORKER_TOKEN", SENTINEL)
    monkeypatch.setenv("DATABASE_URL", SENTINEL)
    source = {
        "src/pages/index.astro": b"---\nconst leak = JSON.stringify(process.env);\n---\n"
        b"<html><body><h1>x</h1><p id=\"env\">{leak}</p></body></html>"
    }
    before = _workspaces()
    result = execute(_request(source, job_id=uuid.uuid4(), business_id=uuid.uuid4(), run_visual_qa=False))
    assert result.status == "succeeded", result.error
    assert _workspaces() <= before  # the job's workspace and toolchain dirs were cleaned up
    rendered = _candidate(result)["index.html"].decode()
    assert 'id="env"' in rendered and "PATH" in rendered  # the page really rendered the environment it saw
    assert SENTINEL not in rendered


def test_a_request_with_a_tampered_source_is_refused():
    request = _request({"src/pages/index.astro": b"<h1>x</h1>"}, job_id=uuid.uuid4(), business_id=uuid.uuid4())
    result = execute(request.model_copy(update={"source_sha256": "0" * 64}))
    assert result.status == "failed" and result.failure_kind is GenerationFailureKind.CANDIDATE_REJECTED


@pytest.fixture()
def stores(tmp_path):
    return (
        PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private")),
        LocalStorageProvider(root_dir=tmp_path / "public"),
    )


def _queued(session, tenant, business, stores, source=None, source_family="gwa-astro"):
    draft = WebsiteDraft(
        tenant_id=tenant.id,
        business_id=business.id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.BUILDING,
    )
    session.add(draft)
    session.flush()
    job = intake.enqueue_generative_build(
        session,
        draft=draft,
        source_files=source or _source_files(),
        idempotency_key=f"job-{uuid.uuid4()}",
        input_sha256="a" * 64,
        artifact_storage=stores[0],
        api_base_url=_r2.API,
        source_family=source_family,
    )
    session.flush()
    return draft, job


def _accept(session, job, result, stores):
    return intake.accept_result(
        session,
        job=job,
        result=result,
        business_config=_r2._business_config(),
        business_truth=_r2._truth(),
        artifact_storage=stores[0],
        asset_storage=stores[1],
    )


def _as_result_for(job, executed_result: ExecutionResult, **update) -> ExecutionResult:
    return executed_result.model_copy(update={"job_id": job.id, "attempt": job.attempts, **update})


def _forged(executed_result: ExecutionResult, **changes: bytes) -> dict[str, str]:
    files = {**_candidate(executed_result), **changes}
    archive = pack_files(files)
    return {"candidate_archive": b64(archive), "candidate_sha256": sha256_hex(archive)}


def test_claim_sends_only_the_jobs_own_build_input(session, tenant, business, stores):
    _, job = _queued(session, tenant, business, stores)
    claimed = intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k")
    assert claimed is not None
    request, token = claimed
    assert request.job_id == job.id and job.status is GenerationJobStatus.RUNNING
    verify_job_token(token, job_id=job.id, attempt=1, signing_key="k")
    assert set(ExecutionRequest.model_fields) == {
        "protocol_version", "job_id", "attempt", "business_id", "api_base_url", "source_family",
        "source_archive", "source_sha256", "offline_assets", "run_visual_qa",
        # R5: supervised-source fields — defaults/empty for a generative job
        "job_kind", "trust_class", "adaptation_plan", "plan_sha256", "site_origin",
    }  # fmt: skip
    assert request.adaptation_plan is None and request.plan_sha256 is None and request.site_origin is None
    assert request.job_kind.value == "generative" and request.trust_class.value == "untrusted_generated"
    assert request.source_family == job.source_family == "gwa-astro"  # H1.1: from the trusted job row
    assert intake.claim_next(session, artifact_storage=stores[0], asset_storage=stores[1], signing_key="k") is None


def test_a_valid_candidate_becomes_a_ready_draft_only_through_the_trusted_gates(
    session, tenant, business, stores, executed
):
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1]), stores)
    assert job.status is GenerationJobStatus.SUCCEEDED, job.error
    assert draft.status is WebsiteDraftStatus.READY and draft.artifact_sha256
    stored = unpack_artifact(stores[0].load(draft.artifact_key))
    assert artifact_sha256(stored) == draft.artifact_sha256  # Build Once / Promote: this exact artifact publishes


def test_a_malicious_host_cannot_bypass_the_truth_contract(session, tenant, business, stores, executed):
    home = _candidate(executed[1])["index.html"]
    forged = _forged(executed[1], **{"index.html": home.replace(b"</main>", b"<p>15 years of experience</p></main>")})
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1], **forged), stores)
    assert job.status is GenerationJobStatus.FAILED and job.failure_kind is GenerationFailureKind.TRUTH_CONTRACT
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED and draft.artifact_key is None


def test_security_headers_are_never_taken_from_the_host(session, tenant, business, stores, executed):
    # H1.1: stricter than re-deriving and accepting — the host's Visual QA ran
    # under the forged policy, so its evidence says nothing about the stored
    # site. The candidate is rejected and nothing is stored.
    forged = _forged(executed[1], _headers=b"/*\n  Content-Security-Policy: default-src *\n")
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1], **forged), stores)
    assert job.failure_kind is GenerationFailureKind.CANDIDATE_REJECTED
    assert "security headers" in (job.error or "")
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED and draft.artifact_key is None


def test_h1_1_the_trusted_job_family_governs_the_csp_not_the_candidate(session, tenant, business, stores, executed):
    # A baseline (gwa-astro) candidate is honest for a gwa-astro job, but a
    # job whose trusted family is Higgsfield expects different headers.
    draft, job = _queued(session, tenant, business, stores, source_family="higgsfield-tanstack-static")
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1]), stores)
    assert job.failure_kind is GenerationFailureKind.CANDIDATE_REJECTED
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED and draft.artifact_key is None


def test_h1_1_stored_headers_are_the_headers_visual_qa_exercised(session, tenant, business, stores, executed):
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1]), stores)
    assert draft.status is WebsiteDraftStatus.READY, job.error
    stored = unpack_artifact(stores[0].load(draft.artifact_key))
    candidate = _candidate(executed[1])
    assert stored.files["_headers"] == candidate["_headers"]  # byte-for-byte, nothing re-derived differently
    # The host recorded the hash of the `_headers` its sandboxed Visual QA served:
    assert executed[1].metadata["headers_sha256"] == hashlib.sha256(stored.files["_headers"]).hexdigest()


def test_h1_1_an_unknown_source_family_is_refused_before_anything_is_stored(session, tenant, business, stores):
    from app.db.models.generation_job import GenerationJob
    from app.publishing.csp_policy import UnsupportedCspRequirementError

    before = session.scalar(select(func.count()).select_from(GenerationJob))
    with pytest.raises(UnsupportedCspRequirementError):
        _queued(session, tenant, business, stores, source_family="anything-goes")
    assert session.scalar(select(func.count()).select_from(GenerationJob)) == before


def test_h1_1_an_idempotency_key_cannot_switch_source_family(session, tenant, business):
    key = f"job-{uuid.uuid4()}"
    jobs.submit_job(session, tenant_id=tenant.id, business_id=business.id, idempotency_key=key, input_sha256="b" * 64)
    with pytest.raises(jobs.GenerationJobError):
        jobs.submit_job(
            session,
            tenant_id=tenant.id,
            business_id=business.id,
            idempotency_key=key,
            input_sha256="b" * 64,
            source_family="higgsfield-tanstack-static",
        )


def test_a_tampered_candidate_is_rejected_and_never_stored(session, tenant, business, stores, executed):
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    _accept(session, job, _as_result_for(job, executed[1], candidate_sha256="0" * 64), stores)
    assert job.failure_kind is GenerationFailureKind.CANDIDATE_REJECTED
    assert draft.status is WebsiteDraftStatus.BUILD_FAILED and draft.artifact_key is None


def test_a_failed_execution_fails_job_and_draft_without_retry(session, tenant, business, stores):
    draft, job = _queued(session, tenant, business, stores, source={"src/pages/index.astro": b"<h1>x</h1>"})
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    failed = ExecutionResult(
        job_id=job.id, attempt=1, status="failed", failure_kind=GenerationFailureKind.RESOURCE_LIMIT, error="timed out"
    )
    _accept(session, job, failed, stores)
    assert job.status is GenerationJobStatus.FAILED and draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert jobs.claim(session, tenant_id=tenant.id, job_id=job.id) is None


def test_results_for_another_job_or_attempt_change_nothing(session, tenant, business, stores, executed):
    draft, job = _queued(session, tenant, business, stores)
    jobs.claim(session, tenant_id=tenant.id, job_id=job.id)
    for update in ({"job_id": uuid.uuid4(), "attempt": 1}, {"job_id": job.id, "attempt": 2}):
        with pytest.raises(intake.IntakeError):
            _accept(session, job, executed[1].model_copy(update=update), stores)
    assert job.status is GenerationJobStatus.RUNNING and draft.status is WebsiteDraftStatus.BUILDING


# --- Internal endpoints ---------------------------------------------------------------


@pytest.fixture()
def api(engine, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.dependencies import get_private_artifact_storage, get_session, get_storage_provider
    from app.main import app

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _session():
        db = factory()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    overrides = {
        get_session: _session,
        get_private_artifact_storage: lambda: PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "p")),
        get_storage_provider: lambda: LocalStorageProvider(root_dir=tmp_path / "public"),
    }
    app.dependency_overrides.update(overrides)
    try:
        yield TestClient(app)
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)


def test_worker_endpoints_do_not_exist_unless_configured(api, monkeypatch):
    monkeypatch.setattr(settings, "generation_worker_token_sha256", None)
    monkeypatch.setattr(settings, "generation_worker_signing_key", None)
    assert api.post("/internal/generation-worker/claim").status_code == 404
    body = ExecutionResult(job_id=uuid.uuid4(), attempt=1, status="failed").model_dump(mode="json")
    assert api.post(f"/internal/generation-worker/jobs/{body['job_id']}/result", json=body).status_code == 404


def test_worker_endpoints_require_the_narrow_credentials(api, monkeypatch):
    token = "worker-" + uuid.uuid4().hex
    monkeypatch.setattr(settings, "generation_worker_token_sha256", hash_worker_token(token))
    monkeypatch.setattr(settings, "generation_worker_signing_key", "signing-" + uuid.uuid4().hex)
    assert api.post("/internal/generation-worker/claim").status_code == 401
    assert api.post("/internal/generation-worker/claim", headers={"Authorization": "Bearer nope"}).status_code == 401
    authorized = {"Authorization": f"Bearer {token}"}
    assert api.post("/internal/generation-worker/claim", headers=authorized).status_code == 204
    body = ExecutionResult(job_id=uuid.uuid4(), attempt=1, status="failed").model_dump(mode="json")
    # The claim credential is NOT a result credential.
    response = api.post(
        f"/internal/generation-worker/jobs/{body['job_id']}/result",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


# --- Worker process ---------------------------------------------------------------------


def test_the_worker_refuses_to_claim_work_on_a_host_that_cannot_isolate(monkeypatch, capsys):
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(worker_main.httpx, "Client", lambda *a, **k: pytest.fail("must not contact the API"))
    assert worker_main.main([]) == worker_main.EX_CONFIG
    assert '"ready": false' in capsys.readouterr().out


def test_the_worker_selftest_reports_this_hosts_enforced_limits(capsys):
    code = worker_main.main(["--selftest"])
    out = capsys.readouterr().out
    assert '"runner": "bubblewrap"' in out
    assert code == (0 if '"missing": []' in out else 1)  # a host without cgroup limits is NOT ready


def test_r4_1_migration_is_additive_reversible_and_the_single_head(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'm.db'}"

    def alembic(*args: str) -> str:
        env = {**os.environ, "DATABASE_URL": db_url}
        done = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def columns() -> set[str]:
        engine = sa.create_engine(db_url)
        try:
            return {c["name"] for c in sa.inspect(engine).get_columns("generation_jobs")}
        finally:
            engine.dispose()

    alembic("upgrade", "a4d2e8f1c7b3")
    assert "source_key" not in columns()
    alembic("upgrade", "c8f4a1d6e2b9")
    assert {"source_key", "source_sha256", "api_base_url"} <= columns()
    alembic("downgrade", "a4d2e8f1c7b3")
    assert "source_key" not in columns()
    alembic("upgrade", "head")
    # H1.1 (d2b7e4a9c1f3, generation_jobs.source_family) and H1.2
    # (e5c1a7b3d9f2, leads.details/client_submission_id) and R5
    # (a7d3f1c5e8b2, supervised source imports) now follow R4.1.
    assert alembic("heads").split() == ["a7d3f1c5e8b2", "(head)"]
