"""v0.2 R4.1 — the control plane's side of the execution protocol.

    enqueue (trusted source) -> claim (ExecutionRequest + job token)
    -> execution host -> accept_result (untrusted candidate) -> READY?

Everything the execution host sends back is untrusted. accept_result
verifies the job/attempt, the candidate's SHA-256 and archive shape, then
hands the files to drafts.judge_generative_candidate — the same
PlatformContract -> TruthContract -> private storage -> READY gates as the
inline path. The host can never mark READY, approve, publish or deploy;
Build Once / Promote is unchanged (what is stored here is what publishes).
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.creative import generation_jobs as jobs
from app.db.models.generation_job import GenerationJob
from app.db.models.website_draft import WebsiteDraft
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import BusinessTruth
from app.domain.enums import GenerationFailureKind, GenerationJobStatus, WebsiteDraftStatus
from app.publishing.drafts import _visual_qa_assets, judge_generative_candidate
from app.repositories.generative_website_artifact import GenerativeWebsiteArtifactRepository
from app.repositories.website_draft import WebsiteDraftRepository
from app.storage import StorageProvider, generate_storage_key
from app.storage.private import PrivateArtifactStorage
from app.worker.auth import issue_job_token
from app.worker.protocol import (
    MAX_CANDIDATE_ARCHIVE_BYTES,
    ExecutionRequest,
    ExecutionResult,
    ProtocolError,
    b64,
    pack_files,
    sha256_hex,
    unb64,
    unpack_candidate,
)

logger = logging.getLogger(__name__)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_SCREENSHOT_BYTES = 10 * 1024**2
_GATE_FAILURE = {
    "platform_contract": GenerationFailureKind.PLATFORM_CONTRACT,
    "truth_contract": GenerationFailureKind.TRUTH_CONTRACT,
    "storage": GenerationFailureKind.CANDIDATE_REJECTED,
}


class IntakeError(Exception):
    """The result cannot be applied (wrong job/attempt/state) — nothing changed."""


def source_storage_key(*, tenant_id: uuid.UUID, business_id: uuid.UUID, job_key: str) -> str:
    return f"generation-sources/{tenant_id}/{business_id}/{job_key}/source.tar.gz"


def enqueue_generative_build(
    session: Session,
    *,
    draft: WebsiteDraft,
    source_files: dict[str, bytes],
    idempotency_key: str,
    input_sha256: str,
    artifact_storage: PrivateArtifactStorage,
    api_base_url: str | None,
) -> GenerationJob:
    """Trusted side, after the provider produced the source: store the
    source privately and queue the build for the execution host."""
    archive = pack_files(source_files)
    key = source_storage_key(
        tenant_id=draft.tenant_id, business_id=draft.business_id, job_key=sha256_hex(idempotency_key.encode())[:32]
    )
    artifact_storage.save(storage_key=key, content=archive, content_type="application/gzip")
    return jobs.submit_job(
        session,
        tenant_id=draft.tenant_id,
        business_id=draft.business_id,
        idempotency_key=idempotency_key,
        input_sha256=input_sha256,
        draft_id=draft.id,
        source_key=key,
        source_sha256=sha256_hex(archive),
        api_base_url=api_base_url,
    )


def claim_next(
    session: Session, *, artifact_storage: PrivateArtifactStorage, asset_storage: StorageProvider, signing_key: str
) -> tuple[ExecutionRequest, str] | None:
    """Claims the oldest queued job and returns ONLY its build input plus a
    job-scoped result token. A source that fails its integrity check fails
    the job here — it is never sent out."""
    candidate = jobs.next_queued_job_id(session)
    if candidate is None:
        return None
    tenant_id, job_id = candidate
    job = jobs.claim(session, tenant_id=tenant_id, job_id=job_id)
    if job is None or job.source_key is None or job.source_sha256 is None:
        return None
    archive = artifact_storage.load(job.source_key)
    if sha256_hex(archive) != job.source_sha256:
        jobs.fail(job, kind=GenerationFailureKind.CANDIDATE_REJECTED, error="stored source failed its integrity check")
        return None
    assets = _visual_qa_assets(session, job.tenant_id, job.business_id, asset_storage)
    request = ExecutionRequest(
        job_id=job.id,
        attempt=job.attempts,
        business_id=job.business_id,
        api_base_url=job.api_base_url,
        source_archive=b64(archive),
        source_sha256=job.source_sha256,
        offline_assets={url: b64(data) for url, data in assets.items()},
    )
    return request, issue_job_token(job_id=job.id, attempt=job.attempts, signing_key=signing_key)


def _fail(job: GenerationJob, draft: WebsiteDraft | None, kind: GenerationFailureKind, error: str) -> None:
    jobs.fail(job, kind=kind, error=error)
    if draft is not None and draft.status is WebsiteDraftStatus.BUILDING:
        draft.status = WebsiteDraftStatus.BUILD_FAILED
        draft.build_error = draft.build_error or f"Isolated build failed ({kind.value})."


def accept_result(
    session: Session,
    *,
    job: GenerationJob,
    result: ExecutionResult,
    business_config: BusinessConfig,
    business_truth: BusinessTruth,
    artifact_storage: PrivateArtifactStorage,
    asset_storage: StorageProvider,
) -> GenerationJob:
    if job.status is not GenerationJobStatus.RUNNING:
        raise IntakeError("job is not running")
    if result.job_id != job.id or result.attempt != job.attempts:
        raise IntakeError("result is for a different job or attempt")
    draft = (
        WebsiteDraftRepository(session).get_for_business(job.tenant_id, job.business_id, job.draft_id)
        if job.draft_id is not None
        else None
    )
    if draft is None or draft.status is not WebsiteDraftStatus.BUILDING:
        _fail(job, draft, GenerationFailureKind.CANDIDATE_REJECTED, "job has no building draft")
        return job

    if result.status == "failed":
        _fail(job, draft, result.failure_kind or GenerationFailureKind.BUILD, result.error or "execution failed")
        return job

    try:
        if result.candidate_archive is None or result.candidate_sha256 is None:
            raise ProtocolError("succeeded result carries no candidate")
        archive = unb64(result.candidate_archive, limit=MAX_CANDIDATE_ARCHIVE_BYTES)
        files = unpack_candidate(archive, expected_sha256=result.candidate_sha256)
        if "index.html" not in files:
            raise ProtocolError("candidate has no index.html")
    except ProtocolError as exc:
        draft.build_error = f"Candidate rejected: {exc}"
        _fail(job, draft, GenerationFailureKind.CANDIDATE_REJECTED, str(exc))
        return job

    gate = judge_generative_candidate(
        draft=draft,
        files=files,
        business_config=business_config,
        business_truth=business_truth,
        artifact_storage=artifact_storage,
        api_base_url=job.api_base_url,
    )
    if gate is not None:
        _fail(job, draft, _GATE_FAILURE[gate], draft.build_error or gate)
        return job

    _record_visual_qa(session, draft=draft, result=result, asset_storage=asset_storage)
    jobs.succeed(job)
    logger.info("generation job succeeded job_id=%s draft_id=%s", job.id, draft.id)
    return job


def _record_visual_qa(
    session: Session, *, draft: WebsiteDraft, result: ExecutionResult, asset_storage: StorageProvider
) -> None:
    """Advisory evidence only (Visual QA never changes draft status):
    findings are stored as data, screenshots only if they are bounded PNGs."""
    report = result.visual_qa
    row = GenerativeWebsiteArtifactRepository(session).get_for_draft(draft.tenant_id, draft.business_id, draft.id)
    if report is None or row is None:
        return
    keys: dict[str, str] = {}
    for name, encoded in list(report.screenshots.items())[:8]:
        try:
            png = unb64(encoded, limit=_MAX_SCREENSHOT_BYTES)
        except ProtocolError:
            continue
        if not png.startswith(_PNG_MAGIC):
            continue
        key = generate_storage_key(business_id=str(draft.business_id), original_filename=f"{name[:40]}.png")
        asset_storage.save(storage_key=key, content=png)
        keys[name[:40]] = key
    row.visual_qa_state = {
        "passed": bool(report.passed),
        "findings": [
            {
                "viewport": str(f.get("viewport", ""))[:50],
                "check": str(f.get("check", ""))[:80],
                "passed": bool(f.get("passed")),
                "detail": str(f.get("detail", ""))[:500],
            }
            for f in report.findings[:100]
        ],
    }
    row.screenshot_keys = keys


def load_job_inputs(session: Session, job: GenerationJob) -> tuple[BusinessConfig, BusinessTruth]:
    """The trusted facts the candidate is judged against, derived exactly
    like the generative route does (stored config, available assets,
    visible reviews) — never taken from the execution host."""
    from app.db.models.business import Business
    from app.domain.business_truth import derive_business_truth
    from app.domain.creative import build_creative_brief
    from app.repositories.business_asset import BusinessAssetRepository
    from app.repositories.business_review import BusinessReviewRepository

    business = session.get(Business, job.business_id)
    if business is None or business.tenant_id != job.tenant_id or business.config is None:
        raise IntakeError("job's business has no configuration")
    config = BusinessConfig.model_validate(business.config)
    assets = BusinessAssetRepository(session).list_for_business(job.tenant_id, job.business_id)
    brief = build_creative_brief(business_config=config, assets=assets)
    truth = derive_business_truth(
        business_config=config,
        assets=brief.available_assets,
        reviews=BusinessReviewRepository(session).list_for_business(job.tenant_id, job.business_id),
    )
    return config, truth
