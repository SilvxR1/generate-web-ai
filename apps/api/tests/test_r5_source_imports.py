"""R5 — supervised source imports through the real product lifecycle:
import -> inspect -> review -> build (execution host) -> trusted intake ->
READY draft -> preview -> approve (exact artifact) -> publish (Build Once /
Promote) -> rollback, and every failure boundary in between.

One REAL supervised build of the synthetic lumen-physio export runs once per
module (the actual claim -> job-token download -> executor path, bubblewrap
runner, real `bun` build and Visual QA). Tests replay that genuine
candidate against fresh databases, unchanged or deliberately tampered.
Publishers are recording doubles: nothing reaches Cloudflare.
"""

import base64
import io
import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.creative import generation_jobs as jobs
from app.creative import source_imports as imports
from app.creative.frontend_engine.sandbox import SandboxLimits, SupervisedProcessRunner, detect_runner
from app.creative.source_adapter.fixtures import lumen_physio_business_config, zip_directory
from app.db.base import Base
from app.db.models.business import Business
from app.db.models.generation_job import GenerationJob
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.source_import import SourceImport, SourceReviewDecision
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.db.models.website import Website
from app.db.models.website_draft import WebsiteDraft
from app.dependencies import (
    get_current_user,
    get_optional_preview_publisher,
    get_preview_publisher,
    get_private_artifact_storage,
    get_session,
    get_storage_provider,
    get_website_publisher,
)
from app.domain.enums import (
    BusinessStatus,
    BusinessVertical,
    GenerationJobKind,
    GenerationJobStatus,
    JobTrustClass,
    SourceImportStatus,
    UserRole,
)
from app.main import app
from app.publishing.artifact_store import artifact_sha256, pack_artifact, unpack_artifact
from app.publishing.errors import WebsitePublisherError
from app.publishing.publisher import (
    PreviewDeployment,
    PreviewPublisher,
    PublishedSite,
    WebsiteArtifact,
    WebsitePublisher,
)
from app.storage import LocalStorageProvider
from app.storage.private import PrivateArtifactStorage
from app.worker import intake
from app.worker.auth import hash_worker_token, issue_job_token
from app.worker.protocol import ExecutionResult, pack_files, sha256_hex, unpack_candidate
from app.worker.source_executor import execute_source_adaptation

FIXTURE = Path(__file__).parent / "fixtures" / "higgsfield_synthetic" / "lumen-physio"
BUSINESS_ID = uuid.uuid5(uuid.NAMESPACE_URL, "https://gwa.local/r5/lumen-physio")
API_ORIGIN = "http://127.0.0.1:8765"
WORKER_TOKEN = "r5-test-worker-token"
SIGNING_KEY = "r5-test-signing-key"


# --- Environment ---------------------------------------------------------------------------


def _configure(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(settings, "supervised_source_imports_enabled", True)
    mp.setattr(settings, "generation_worker_token_sha256", hash_worker_token(WORKER_TOKEN))
    mp.setattr(settings, "generation_worker_signing_key", SIGNING_KEY)
    mp.setenv("PUBLIC_API_BASE_URL", API_ORIGIN)


def _seed(session: Session) -> tuple[Tenant, User, Business]:
    tenant = Tenant(name="R5 tenant")
    session.add(tenant)
    session.flush()
    user = User(email="operator@r5.example", hashed_password="x")
    session.add(user)
    session.flush()
    session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
    business = Business(
        id=BUSINESS_ID,
        tenant_id=tenant.id,
        name="Lumen Physio",
        slug="lumen-physio",
        vertical=BusinessVertical.CLINIC,
        raw_description="Fictional R5 business.",
        status=BusinessStatus.DRAFT,
        config=lumen_physio_business_config().model_dump(mode="json"),
    )
    session.add(business)
    session.flush()
    return tenant, user, business


def _variant_zip(tmp: Path, name: str, edits: dict[str, str | bytes] | None = None) -> bytes:
    source = tmp / name / "lumen-physio"
    shutil.copytree(FIXTURE, source)
    for rel, content in (edits or {}).items():
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    return zip_directory(source, tmp / f"{name}.zip").read_bytes()


class RecordingPublisher(WebsitePublisher):
    def __init__(self) -> None:
        self.artifacts: list[WebsiteArtifact] = []
        self.fail = False

    def publish(self, *, site_id, artifact):
        if self.fail:
            raise WebsitePublisherError("simulated Pages failure")
        self.artifacts.append(artifact)
        return PublishedSite(deployment_id=f"prod-{len(self.artifacts)}", url="https://example.pages.dev", live=True)

    def get_status(self, deployment_id):
        raise NotImplementedError

    def unpublish(self, deployment_id):
        pass


class RecordingPreviewPublisher(PreviewPublisher):
    def __init__(self) -> None:
        self.deployed: list[WebsiteArtifact] = []

    def publish_preview(self, *, branch, artifact):
        self.deployed.append(artifact)
        return PreviewDeployment(deployment_id=f"dep-{len(self.deployed)}", url="https://abc.preview.pages.dev")

    def retire_preview(self, *, branch, deployment_id):
        pass


@dataclass
class Env:
    client: TestClient
    session: Session
    tenant: Tenant
    user: User
    business: Business
    storage: PrivateArtifactStorage
    publisher: RecordingPublisher
    preview: RecordingPreviewPublisher
    tmp: Path

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Tenant-Id": str(self.tenant.id)}

    def url(self, suffix: str = "") -> str:
        return f"/businesses/{self.business.id}/source-imports{suffix}"

    def upload(self, data: bytes, name: str = "export.zip"):
        return self.client.post(self.url(), headers=self.headers, files={"file": (name, data, "application/zip")})

    def worker(self, token: str = WORKER_TOKEN) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


_OVERRIDDEN = (
    get_session,
    get_private_artifact_storage,
    get_storage_provider,
    get_current_user,
    get_website_publisher,
    get_preview_publisher,
    get_optional_preview_publisher,
)


@pytest.fixture()
def env(session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _configure(monkeypatch)
    tenant, user, business = _seed(session)
    storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp_path / "private"))
    publisher, preview = RecordingPublisher(), RecordingPreviewPublisher()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_private_artifact_storage] = lambda: storage
    app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(root_dir=tmp_path / "public")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_website_publisher] = lambda: publisher
    app.dependency_overrides[get_preview_publisher] = lambda: preview
    app.dependency_overrides[get_optional_preview_publisher] = lambda: preview
    try:
        yield Env(TestClient(app), session, tenant, user, business, storage, publisher, preview, tmp_path)
    finally:
        for dep in _OVERRIDDEN:
            app.dependency_overrides.pop(dep, None)


# --- One real supervised build (module scope) ------------------------------------------------


@dataclass
class Built:
    zip_bytes: bytes
    plan_sha256: str
    result: ExecutionResult


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    """The genuine worker path once: import -> build queued -> claim ->
    job-token download -> execute (bubblewrap, real bun build, Visual QA)."""
    if shutil.which("bun") is None:
        pytest.skip("bun is required for the real supervised build")
    tmp = tmp_path_factory.mktemp("r5-build")
    zip_bytes = _variant_zip(tmp, "lumen")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with pytest.MonkeyPatch.context() as mp, sessionmaker(bind=engine, expire_on_commit=False)() as session:
        _configure(mp)
        _, user, business = _seed(session)
        storage = PrivateArtifactStorage(LocalStorageProvider(root_dir=tmp / "private"))
        row = imports.import_source(
            session,
            tenant_id=business.tenant_id,
            business_id=business.id,
            user=user,
            filename="lumen.zip",
            data=zip_bytes,
            artifact_storage=storage,
        )
        assert row.status is SourceImportStatus.READY_TO_BUILD, row.inspection.get("findings")
        imports.start_build(session, row=row, user=user, artifact_storage=storage)
        claimed = intake.claim_next(
            session,
            artifact_storage=storage,
            asset_storage=LocalStorageProvider(root_dir=tmp / "public"),
            signing_key=SIGNING_KEY,
            isolation="bubblewrap",
        )
        assert claimed is not None
        request, _ = claimed
        job = session.get(GenerationJob, request.job_id)
        assert job is not None
        result = execute_source_adaptation(request, intake.download_source(job, storage), runner=detect_runner())
        assert result.status == "succeeded", result.error
        return Built(zip_bytes=zip_bytes, plan_sha256=str(row.plan_sha256), result=result)


def _import_and_build(env: Env, data: bytes) -> tuple[dict, GenerationJob, str]:
    """Import + build via the API; claim via the worker endpoint."""
    created = env.upload(data)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "ready_to_build", body["open_reviews"]
    queued = env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers)
    assert queued.status_code == 202, queued.text
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    assert claim.status_code == 200, claim.text
    job = env.session.get(GenerationJob, uuid.UUID(claim.json()["request"]["job_id"]))
    assert job is not None
    return body, job, claim.json()["job_token"]


def _submit(env: Env, job: GenerationJob, token: str, result: ExecutionResult):
    result = result.model_copy(update={"job_id": job.id, "attempt": job.attempts})
    return env.client.post(
        f"/internal/generation-worker/jobs/{job.id}/result",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        content=result.model_dump_json(),
    )


def _tampered(result: ExecutionResult, mutate=None, **metadata: object) -> ExecutionResult:
    files = unpack_candidate(
        base64.b64decode(result.candidate_archive or ""), expected_sha256=str(result.candidate_sha256)
    )
    if mutate is not None:
        mutate(files)
    archive = pack_files(files)
    return result.model_copy(
        update={
            "candidate_archive": base64.b64encode(archive).decode(),
            "candidate_sha256": sha256_hex(archive),
            "metadata": {**result.metadata, **metadata},
        }
    )


def _state(env: Env, import_id: str) -> dict:
    response = env.client.get(env.url(f"/{import_id}"), headers=env.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _ready(env: Env, built: Built) -> dict:
    body, job, token = _import_and_build(env, built.zip_bytes)
    assert _submit(env, job, token, built.result).status_code == 204
    return _state(env, body["id"])


# --- Gate, import and archive policy ----------------------------------------------------------


def test_the_feature_is_off_by_default_and_separate_from_the_generative_gate(env, monkeypatch):
    monkeypatch.setattr(settings, "supervised_source_imports_enabled", False)
    assert settings.generative_website_builds_enabled is False
    capability = env.client.get(env.url("/capability"), headers=env.headers).json()
    assert capability["enabled"] is False and capability["supervised_only"] is True
    assert env.upload(b"PK\x03\x04").status_code == 403
    assert env.client.get(env.url(), headers=env.headers).status_code == 403


@pytest.mark.parametrize("data", [b"not a zip at all", b"PK\x03\x04garbage"])
def test_malformed_archives_are_rejected_and_nothing_is_stored(env, data):
    response = env.upload(data)
    assert response.status_code == 422 and response.json()["error"]["code"] == "source_not_zip"
    assert env.session.scalars(select(SourceImport)).all() == []
    assert not list((env.tmp / "private").rglob("*.zip")) if (env.tmp / "private").exists() else True


def _raw_zip(entries: list) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for info, data in entries:
            archive.writestr(info, data)
    return buffer.getvalue()


def test_zip_slip_and_symlinks_are_rejected_before_anything_is_stored(env):
    slip = _raw_zip([("site/package.json", b"{}"), ("../../etc/evil", b"x")])
    link = zipfile.ZipInfo("site/link")
    link.external_attr = 0o120777 << 16
    symlink = _raw_zip([("site/package.json", b"{}"), (link, b"/etc/passwd")])
    for data in (slip, symlink):
        response = env.upload(data)
        assert response.status_code == 422 and response.json()["error"]["code"] == "source_archive_rejected"
    assert env.session.scalars(select(SourceImport)).all() == []


def test_an_oversized_archive_is_rejected(env, monkeypatch):
    monkeypatch.setattr(settings, "supervised_source_max_bytes", 1024)
    assert env.upload(_variant_zip(env.tmp, "big")).status_code == 413


def test_an_unsupported_source_is_recorded_as_blocked_and_can_never_build(env):
    package = json.loads((FIXTURE / "package.json").read_text())
    package["dependencies"].pop("@tanstack/react-start")
    response = env.upload(_variant_zip(env.tmp, "unsupported", {"package.json": json.dumps(package)}))
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "blocked" and body["plan_sha256"] is None
    assert any(f["code"] == "no_family_adapter" and f["open"] for f in body["inspection"]["findings"])
    assert env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers).status_code == 409


def test_the_snapshot_is_immutable_content_addressed_and_the_inspection_is_readable(env):
    data = _variant_zip(env.tmp, "lumen")
    body = env.upload(data, name="lumen-physio.zip").json()
    row = env.session.get(SourceImport, uuid.UUID(body["id"]))
    assert row is not None and row.zip_sha256 == sha256_hex(data) == body["zip_sha256"]
    assert env.storage.load(row.snapshot_key) == data
    assert body["adapter"] == "higgsfield-tanstack-static@1.0.0"
    assert body["source_family"] == "higgsfield-tanstack-static"
    inspection = body["inspection"]
    assert inspection["manifest"]["framework"]["router"] == "tanstack-file-routes"
    assert {f["role"] for f in inspection["forms"][0]["fields"]} >= {"name", "email", "service", "consent"}
    assert inspection["build"]["expected_pages"] and inspection["plan"]["operations"] > 0
    assert body["site_origin"] == f"https://site-{BUSINESS_ID.hex}.pages.dev" and body["api_base_url"] == API_ORIGIN
    diagnostics = env.client.get(env.url(f"/{body['id']}/diagnostics"), headers=env.headers).json()
    assert diagnostics["plan_sha256"] == body["plan_sha256"] and diagnostics["manifest"]["manifest_sha256"]


# --- Review gate --------------------------------------------------------------------------------

_HERO = "src/features/landing/Hero.tsx"
_TRACKER = (FIXTURE / _HERO).read_text().replace(
    "export function Hero() {",
    'export function Hero() {\n  if (typeof window !== "undefined") (window as any).gtag?.("event");',
)


def _needs_review(env: Env) -> dict:
    body = env.upload(_variant_zip(env.tmp, "review", {_HERO: _TRACKER})).json()
    assert body["status"] == "needs_review" and body["open_reviews"] == ["analytics_or_tracking:google-analytics"]
    return body


def _decide(env: Env, body: dict, finding_id: str, decision: str = "approved", rationale: str = "ok"):
    return env.client.post(
        env.url(f"/{body['id']}/decisions"),
        headers=env.headers,
        json={"finding_id": finding_id, "decision": decision, "rationale": rationale},
    )


def test_review_findings_block_the_build_until_an_audited_approval_for_this_exact_plan(env):
    body = _needs_review(env)
    assert env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers).status_code == 409
    decided = _decide(env, body, body["open_reviews"][0], rationale="Owner removes it before launch.")
    assert decided.status_code == 200 and decided.json()["status"] == "ready_to_build"
    [decision] = decided.json()["decisions"]
    assert decision["actor_email"] == "operator@r5.example" and decision["snapshot_sha256"] == body["zip_sha256"]
    assert decision["plan_sha256"] == body["plan_sha256"] and decision["created_at"]


def test_a_blocker_can_never_be_approved_and_a_rationale_is_required(env):
    body = _needs_review(env)
    blocker = next(f["id"] for f in body["inspection"]["findings"] if f["severity"] == "blocker")
    assert _decide(env, body, blocker).status_code == 409
    assert _decide(env, body, body["open_reviews"][0], rationale="   ").status_code == 422


def test_a_rejected_finding_stops_the_import(env):
    body = _needs_review(env)
    assert _decide(env, body, body["open_reviews"][0], "rejected", "Not acceptable.").json()["status"] == "rejected"
    assert env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers).status_code == 409


def _rename_service(env: Env) -> None:
    config = lumen_physio_business_config()
    services = [
        s.model_copy(update={"name": "Osteopathy and manual therapy"}) if s.id == "osteopathy" else s
        for s in config.business_profile.services
    ]
    profile = config.business_profile.model_copy(update={"services": services})
    env.business.config = config.model_copy(update={"business_profile": profile}).model_dump(mode="json")
    env.session.flush()


def test_a_business_truth_change_invalidates_the_plan_and_its_approvals(env):
    body = _needs_review(env)
    _decide(env, body, body["open_reviews"][0])
    _rename_service(env)
    assert _state(env, body["id"])["status"] == "stale"
    assert env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers).status_code == 409
    again = env.client.post(env.url(f"/{body['id']}/reinspect"), headers=env.headers).json()
    assert again["plan_sha256"] != body["plan_sha256"]  # a new plan identity
    assert again["status"] == "needs_review" and again["decisions"] == []  # the old approval never carries over
    assert len(env.session.scalars(select(SourceReviewDecision)).all()) == 1  # audit trail kept


def test_a_changed_snapshot_is_refused_at_build(env):
    body = env.upload(_variant_zip(env.tmp, "lumen")).json()
    row = env.session.get(SourceImport, uuid.UUID(body["id"]))
    assert row is not None
    (env.tmp / "private" / row.snapshot_key).write_bytes(b"PK\x03\x04tampered")
    response = env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "source_snapshot_integrity"


def test_a_build_is_never_run_by_the_api_without_a_worker(env, monkeypatch):
    body = env.upload(_variant_zip(env.tmp, "lumen")).json()
    monkeypatch.setattr(settings, "generation_worker_signing_key", None)
    response = env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers)
    assert response.status_code == 503 and response.json()["error"]["code"] == "build_worker_not_configured"


# --- Worker boundary ------------------------------------------------------------------------------


def test_the_build_job_carries_only_scoped_inputs_and_only_trusted_isolation_claims_it(env):
    body = env.upload(_variant_zip(env.tmp, "lumen")).json()
    env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers)
    job = env.session.scalars(select(GenerationJob)).one()
    assert job.job_kind is GenerationJobKind.SOURCE_ADAPTATION and job.trust_class is JobTrustClass.SUPERVISED_SOURCE
    assert job.plan_sha256 == body["plan_sha256"] and job.source_sha256 == body["zip_sha256"]
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    request = claim.json()["request"]
    assert request["source_archive"] is None and request["plan_sha256"] == body["plan_sha256"]
    assert request["site_origin"] == body["site_origin"] and request["offline_assets"] == {}
    serialized = json.dumps(claim.json())
    for secret in (SIGNING_KEY, WORKER_TOKEN, "DATABASE_URL", "hashed_password"):
        assert secret not in serialized
    token = claim.json()["job_token"]
    url = f"/internal/generation-worker/jobs/{job.id}/source"
    source = env.client.get(url, headers={"Authorization": f"Bearer {token}"})
    assert source.status_code == 200 and sha256_hex(source.content) == body["zip_sha256"]
    other = issue_job_token(job_id=uuid.uuid4(), attempt=1, signing_key=SIGNING_KEY)
    assert env.client.get(url, headers={"Authorization": f"Bearer {other}"}).status_code == 401
    assert env.client.get(url).status_code == 401


def test_a_supervised_worker_never_receives_ai_generated_code(env):
    jobs.submit_job(
        env.session,
        tenant_id=env.tenant.id,
        business_id=env.business.id,
        idempotency_key="gen-1",
        input_sha256="0" * 64,
        source_key="k",
        source_sha256="0" * 64,
    )
    with pytest.raises(jobs.GenerationJobError):
        jobs.submit_job(
            env.session,
            tenant_id=env.tenant.id,
            business_id=env.business.id,
            idempotency_key="gen-2",
            input_sha256="0" * 64,
            source_key="k",
            source_sha256="0" * 64,
            trust_class=JobTrustClass.SUPERVISED_SOURCE,
        )
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    assert claim.status_code == 204


def test_the_supervised_runner_is_honest_about_what_it_does_not_isolate():
    limits = SupervisedProcessRunner().limits_enforced()
    assert limits["filesystem_isolation"] is False and limits["network_isolation"] is False
    assert limits["pid_isolation"] is False and limits["wall_timeout"] is True


def test_the_supervised_runner_passes_only_the_allowlisted_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GWA_WORKER_TOKEN", "must-not-leak")
    SupervisedProcessRunner().run(
        ["/bin/sh", "-c", "env > seen.txt"],
        workspace=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        limits=SandboxLimits(address_space_fallback=False),
        step="env",
    )
    seen = (tmp_path / "seen.txt").read_text()
    assert "must-not-leak" not in seen and "GWA_WORKER_TOKEN" not in seen


# --- Real build -> trusted intake ---------------------------------------------------------------


def test_the_real_worker_candidate_becomes_an_immutable_ready_artifact(env, built):
    state = _ready(env, built)
    assert state["stage"] == "preview_ready" and state["status"] == "preview_ready"
    draft = state["draft"]
    assert draft["status"] == "ready" and draft["artifact_sha256"]
    assert draft["visual_qa_current"] is True and draft["visual_qa_passed"] is True
    assert state["plan_sha256"] == built.plan_sha256
    row = env.session.get(WebsiteDraft, uuid.UUID(draft["id"]))
    assert row is not None and row.artifact_key is not None


def _replace(path: str, old: bytes, new: bytes):
    return lambda f: f.__setitem__(path, f[path].replace(old, new, 1))


_OTHER_BUSINESS = str(uuid.uuid4()).encode()
_CANDIDATE_TAMPERING = {
    "wrong source identity": lambda r: _tampered(r, snapshot_sha256="0" * 64),
    "wrong plan identity": lambda r: _tampered(r, plan_sha256="1" * 64),
    "wrong CSP": lambda r: _tampered(r, _replace("_headers", b"'self'", b"*")),
    "server output": lambda r: _tampered(r, lambda f: f.__setitem__("server/index.mjs", b"export default {}")),
    "executable": lambda r: _tampered(r, lambda f: f.__setitem__("assets/tool", b"\x7fELF\x02")),
    "missing page": lambda r: _tampered(r, lambda f: f.pop("studio/index.html")),
    "other business": lambda r: _tampered(r, _replace("index.html", str(BUSINESS_ID).encode(), _OTHER_BUSINESS)),
    "malformed archive": lambda r: r.model_copy(update={"candidate_archive": base64.b64encode(b"nope").decode()}),
    "failed contract": lambda r: _tampered(
        r, _replace("index.html", b"</body>", b'<a href="mailto:fake@lumen.example">x</a></body>')
    ),
}


@pytest.mark.parametrize("label", sorted(_CANDIDATE_TAMPERING))
def test_intake_rejects_every_candidate_that_is_not_exactly_what_the_job_asked_for(env, built, label):
    body, job, token = _import_and_build(env, built.zip_bytes)
    assert _submit(env, job, token, _CANDIDATE_TAMPERING[label](built.result)).status_code == 204
    state = _state(env, body["id"])
    assert state["status"] == "build_failed", label
    assert state["draft"]["status"] == "build_failed" and state["draft"]["artifact_sha256"] is None, label
    assert state["error"], label


def test_an_untrusted_generated_result_from_a_supervised_runner_is_rejected(env, built):
    body, job, token = _import_and_build(env, built.zip_bytes)
    job.trust_class = JobTrustClass.UNTRUSTED_GENERATED  # as if it were AI-generated code
    env.session.flush()
    _submit(env, job, token, _tampered(built.result, runner="supervised-process"))
    assert _state(env, body["id"])["status"] == "build_failed"


def test_a_business_truth_change_during_the_build_rejects_the_candidate(env, built):
    body, job, token = _import_and_build(env, built.zip_bytes)
    _rename_service(env)
    _submit(env, job, token, built.result)
    state = _state(env, body["id"])
    # refused at intake, then STALE: only a re-inspection (new plan) can continue
    assert state["status"] == "stale" and state["draft"]["status"] == "build_failed"
    assert "stale" in (state["draft"]["build_error"] or "")


# --- Preview, approve, publish, rollback -----------------------------------------------------------


def _draft_url(env: Env, draft_id: str, action: str) -> str:
    return f"/businesses/{env.business.id}/website-drafts/{draft_id}/{action}"


def test_preview_serves_the_exact_artifact_and_does_not_approve(env, built):
    state = _ready(env, built)
    draft = state["draft"]
    assert env.client.post(_draft_url(env, draft["id"], "preview"), headers=env.headers).status_code == 200
    assert artifact_sha256(env.preview.deployed[-1]) == draft["artifact_sha256"]
    assert _state(env, state["id"])["draft"]["status"] == "ready"


def test_approval_binds_to_the_exact_artifact_and_publish_promotes_those_bytes(env, built):
    state = _ready(env, built)
    draft = state["draft"]
    env.client.post(_draft_url(env, draft["id"], "preview"), headers=env.headers)
    assert env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers).status_code == 200
    row = env.session.get(WebsiteDraft, uuid.UUID(draft["id"]))
    assert row is not None and row.approved_artifact_sha256 == draft["artifact_sha256"]
    assert _state(env, state["id"])["stage"] == "approved"
    published = env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers)
    assert published.status_code == 200, published.text
    previewed, live = env.preview.deployed[-1], env.publisher.artifacts[-1]
    assert artifact_sha256(previewed) == artifact_sha256(live) == draft["artifact_sha256"]  # no rebuild
    assert live.files == previewed.files
    assert _state(env, state["id"])["stage"] == "published"


def test_failed_or_stale_visual_qa_blocks_approval(env, built):
    assert built.result.visual_qa is not None
    failing = built.result.model_copy(update={"visual_qa": built.result.visual_qa.model_copy(update={"passed": False})})
    body, job, token = _import_and_build(env, built.zip_bytes)
    _submit(env, job, token, failing)
    draft = _state(env, body["id"])["draft"]
    refused = env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers)
    assert refused.status_code == 409 and "Visual QA failed" in refused.json()["error"]["message"]
    row = env.session.scalars(select(GenerativeWebsiteArtifact)).one()
    row.visual_qa_state = {**row.visual_qa_state, "passed": True, "artifact_sha256": "f" * 64}  # another artifact
    env.session.flush()
    stale = env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers)
    assert stale.status_code == 409 and "stale" in stale.json()["error"]["message"]


def test_a_business_truth_change_after_the_build_blocks_approval_and_publish(env, built):
    draft = _ready(env, built)["draft"]
    assert env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers).status_code == 200
    _rename_service(env)
    refused = env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers)
    assert refused.status_code == 409 and env.publisher.artifacts == []


def test_an_artifact_changed_after_approval_is_never_published(env, built):
    draft = _ready(env, built)["draft"]
    env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers)
    row = env.session.get(WebsiteDraft, uuid.UUID(draft["id"]))
    assert row is not None and row.artifact_key is not None
    row.approved_artifact_sha256 = "e" * 64  # an approval given for different bytes
    env.session.flush()
    assert env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers).status_code == 409
    row.approved_artifact_sha256 = row.artifact_sha256
    env.session.flush()
    # storage tampering after approval: different (valid) content under the same key
    original = unpack_artifact(env.storage.load(row.artifact_key))
    forged = {**original.files, "index.html": original.files["index.html"].replace(b"Lumen", b"Forged", 1)}
    forged_archive = pack_artifact(WebsiteArtifact(files=forged, entry_point="index.html"))
    (env.tmp / "private" / row.artifact_key).write_bytes(forged_archive)
    assert env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers).status_code == 409
    assert env.publisher.artifacts == []


def test_a_failed_publish_leaves_the_live_site_and_the_approval_unchanged(env, built):
    state = _ready(env, built)
    draft = state["draft"]
    env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers)
    env.publisher.fail = True
    assert env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers).status_code >= 400
    assert all(w.deploy_url is None for w in env.session.scalars(select(Website)).all())  # nothing went live
    assert env.publisher.artifacts == []
    assert _state(env, state["id"])["draft"]["status"] == "approved"


def _second_artifact(built: Built) -> ExecutionResult:
    """Artifact B: the same site with one visible copy change."""
    return _tampered(built.result, _replace("studio/index.html", b"The studio", b"Our studio"))


def _publish(env: Env, result: ExecutionResult) -> str:
    body, job, token = _import_and_build(env, _variant_zip(env.tmp, f"v{uuid.uuid4().hex[:6]}"))
    assert _submit(env, job, token, result).status_code == 204
    draft = _state(env, body["id"])["draft"]
    assert env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers).status_code == 200
    assert env.client.post(_draft_url(env, draft["id"], "publish"), headers=env.headers).status_code == 200
    return draft["artifact_sha256"]


def _previous_version(env: Env) -> dict:
    """The one published version that is not current (A, after B went live)."""
    versions = env.client.get(f"/businesses/{env.business.id}/website/versions", headers=env.headers).json()
    [previous] = [v for v in versions if not v["is_current"]]
    return previous


def test_rollback_restores_the_exact_previous_artifact_without_rebuilding(env, built):
    sha_a = _publish(env, built.result)
    sha_b = _publish(env, _second_artifact(built))
    assert sha_a != sha_b and artifact_sha256(env.publisher.artifacts[-1]) == sha_b
    version_a = _previous_version(env)
    rolled = env.client.post(
        f"/businesses/{env.business.id}/website/versions/{version_a['id']}/rollback", headers=env.headers
    )
    assert rolled.status_code == 200, rolled.text
    assert artifact_sha256(env.publisher.artifacts[-1]) == sha_a  # the exact bytes of A, not a rebuild


def test_a_failed_rollback_leaves_the_live_artifact_unchanged(env, built):
    _publish(env, built.result)
    sha_b = _publish(env, _second_artifact(built))
    live_before = env.session.scalars(select(Website)).one().deploy_url
    version_a = _previous_version(env)
    env.publisher.fail = True
    failed = env.client.post(
        f"/businesses/{env.business.id}/website/versions/{version_a['id']}/rollback", headers=env.headers
    )
    assert failed.status_code >= 400
    assert artifact_sha256(env.publisher.artifacts[-1]) == sha_b
    assert env.session.scalars(select(Website)).one().deploy_url == live_before


def test_every_lifecycle_stage_is_distinct(env):
    body = env.upload(_variant_zip(env.tmp, "lumen")).json()
    assert body["stage"] == "ready_to_build"
    env.client.post(env.url(f"/{body['id']}/build"), headers=env.headers)
    assert _state(env, body["id"])["stage"] == "queued"
    env.client.post("/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"})
    assert _state(env, body["id"])["stage"] == "building"
    assert env.session.scalars(select(GenerationJob)).one().status is GenerationJobStatus.RUNNING


def test_r5_migration_is_the_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    # R5.2 (b8e2f4a6c1d3) is the only revision after R5's.
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["b8e2f4a6c1d3"]
    assert script.get_revision("b8e2f4a6c1d3").down_revision == "a7d3f1c5e8b2"
