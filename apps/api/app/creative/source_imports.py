"""R5 — supervised source imports: the product workflow around the H2
source adapter.

    upload ZIP -> validate (static; zip-slip/symlink/size policy) -> immutable
    snapshot (private storage, content-addressed) -> SourceManifest ->
    supportability -> PROPOSED AdaptationPlan -> human review (audited,
    bound to snapshot + plan) -> build job on the execution host ->
    trusted intake (app.worker.intake) -> READY draft -> preview ->
    approve (exact artifact) -> publish (Build Once / Promote) -> rollback

Everything here runs in the trusted API process and never executes the
imported source: inspection and planning are static (H2 inspect_export).
The build runs on the execution host (app.worker), which receives only the
snapshot, the stored plan and a job identity.

Supervised, not automatic: an operator uploads an export produced and
reviewed OUTSIDE GWA (Higgsfield Supercomputer). Nothing here calls
Higgsfield.
"""

import io
import json
import logging
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.creative import generation_jobs as jobs
from app.creative.business_inputs import BusinessInputsError, business_truth_sha256, load_business_inputs
from app.creative.source_adapter.pipeline import Planned, inspect_export
from app.creative.source_adapter.plan import AdaptationPlan, canonical_json, sha256_hex
from app.creative.source_adapter.records import AdapterError
from app.db.models.custom_domain import CustomDomain
from app.db.models.generation_job import GenerationJob
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.source_import import SourceImport, SourceReviewDecision
from app.db.models.user import User
from app.db.models.website_draft import WebsiteDraft
from app.domain.business_config import BusinessConfig
from app.domain.business_truth import BusinessTruth
from app.domain.enums import (
    DomainStatus,
    GenerationEngine,
    GenerationJobKind,
    GenerationJobStatus,
    JobTrustClass,
    ReviewDecisionKind,
    SourceImportStatus,
    WebsiteDraftStatus,
)
from app.publishing.public_origin import public_origin_problem, resolve_public_api_base_url
from app.publishing.qa_evidence import evidence_is_current
from app.publishing.service import website_project_name
from app.qa.platform_contract import PLATFORM_CONTRACT_VERSION
from app.storage.private import PrivateArtifactStorage

logger = logging.getLogger(__name__)

MAX_RATIONALE_CHARS = 2000
_REINSPECTABLE = frozenset(
    {
        SourceImportStatus.BLOCKED,
        SourceImportStatus.NEEDS_REVIEW,
        SourceImportStatus.REJECTED,
        SourceImportStatus.READY_TO_BUILD,
        SourceImportStatus.STALE,
        SourceImportStatus.BUILD_FAILED,
    }
)
_BUILDABLE = frozenset({SourceImportStatus.READY_TO_BUILD, SourceImportStatus.BUILD_FAILED})
_TRUTH_SENSITIVE = _REINSPECTABLE - {SourceImportStatus.STALE}


class SourceImportError(Exception):
    """A request the workflow refuses; the message is safe to show."""

    def __init__(self, message: str, *, code: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def snapshot_storage_key(*, tenant_id: uuid.UUID, business_id: uuid.UUID, zip_sha256: str) -> str:
    return f"source-snapshots/{tenant_id}/{business_id}/{zip_sha256}.zip"


def _import_prefix(row: SourceImport) -> str:
    return f"source-imports/{row.tenant_id}/{row.business_id}/{row.id}"


def site_origin_for(session: Session, *, tenant_id: uuid.UUID, business_id: uuid.UUID) -> str:
    """The canonical origin the site is built for: the business's ACTIVE
    custom domain, else its Cloudflare Pages project domain."""
    domain = session.scalar(
        select(CustomDomain).where(
            CustomDomain.tenant_id == tenant_id,
            CustomDomain.business_id == business_id,
            CustomDomain.status == DomainStatus.ACTIVE,
        )
    )
    if domain is not None:
        return f"https://{domain.domain}"
    return f"https://{website_project_name(business_id)}.pages.dev"


def _inputs(session: Session, tenant_id: uuid.UUID, business_id: uuid.UUID) -> tuple[BusinessConfig, BusinessTruth]:
    try:
        return load_business_inputs(session, tenant_id=tenant_id, business_id=business_id)
    except BusinessInputsError as exc:
        raise SourceImportError(
            "Complete the business profile before importing a website.", code="business_not_configured", status_code=409
        ) from exc


def _save_once(storage: PrivateArtifactStorage, key: str, content: bytes, content_type: str) -> None:
    """Identity-named objects are written once and never overwritten; an
    existing object must already hold exactly the same bytes."""
    if storage.exists(key):
        if sha256_hex(storage.load(key)) != sha256_hex(content):
            raise SourceImportError(
                "A stored source object does not match its identity; nothing was changed.",
                code="source_storage_conflict",
                status_code=409,
            )
        return
    storage.save(storage_key=key, content=content, content_type=content_type)


# --- Inspection ---------------------------------------------------------------------------

_FINDING_KEYS = ("id", "code", "severity", "subject", "detail", "source", "resolution", "approval", "open")


def _summary(planned: Planned) -> dict:
    """What Studio shows (normal operation never requires raw JSON)."""
    m, s, plan = planned.manifest, planned.supportability, planned.plan
    report = s.to_dict()
    summary: dict = {
        "manifest": m.summary(),
        "supportability": {"status": s.status, "adapter": s.adapter, "counts": report["counts"]},
        "findings": [{k: f.get(k) for k in _FINDING_KEYS} for f in report["findings"]],
        "security": [{k: v for k, v in i.items() if k in ("code", "path", "detail", "live")} for i in m.security],
        "external_origins": [
            {"origin": o["origin"], "context": o["context"], "client_live": o["live"]} for o in m.external_origins
        ],
        "forms": [],
        "fact_bindings": [],
        "build": None,
        "plan": None,
        "readiness": [],
        "csp": None,
        "site": None,
    }
    if plan is not None:
        summary.update(
            forms=plan.form_mappings,
            fact_bindings=plan.fact_bindings,
            build=plan.build,
            plan={"plan_sha256": plan.plan_sha256, **plan.summary},
            readiness=plan.readiness_findings,
            csp=plan.csp,
            site=plan.site,
        )
    return summary


def _inspect_into(
    session: Session, row: SourceImport, *, data: bytes, artifact_storage: PrivateArtifactStorage
) -> None:
    config, truth = _inputs(session, row.tenant_id, row.business_id)
    with tempfile.TemporaryDirectory(prefix="gwa-source-import-") as tmp:
        zip_path = Path(tmp) / "source.zip"
        zip_path.write_bytes(data)
        try:
            planned = inspect_export(
                zip_path,
                Path(tmp) / "work",
                config,
                site_origin=row.site_origin,
                allow_pending_review=True,
                business_truth=truth,
            )
        except (AdapterError, zipfile.BadZipFile, ValueError, OSError) as exc:
            logger.info("source import refused business=%s reason=%s", row.business_id, type(exc).__name__)
            raise SourceImportError(
                f"This archive is not a website export GWA can accept: {str(exc)[:300]}",
                code="source_archive_rejected",
                status_code=422,
            ) from exc
    manifest = planned.manifest
    manifest_key = f"{_import_prefix(row)}/manifest-{manifest.sha256}.json"
    _save_once(artifact_storage, manifest_key, canonical_json(manifest.to_dict()), "application/json")
    row.manifest_sha256 = manifest.sha256
    row.manifest_key = manifest_key
    row.supportability = planned.supportability.status
    row.business_truth_sha256 = business_truth_sha256(truth)
    adapter = planned.plan.adapter if planned.plan is not None else None
    row.adapter_id = adapter["adapter_id"] if adapter else None
    row.adapter_version = adapter["version"] if adapter else None
    row.adapter_contract_version = adapter["contract_version"] if adapter else None
    row.source_family = adapter["family"] if adapter else None
    row.inspection = _summary(planned)
    row.error = None
    if planned.plan is None:
        row.plan_sha256 = None
        row.plan_key = None
        row.status = SourceImportStatus.BLOCKED
        return
    plan = planned.plan
    plan_key = f"{_import_prefix(row)}/plan-{plan.plan_sha256}.json"
    _save_once(artifact_storage, plan_key, canonical_json(plan.to_dict(include_binary=True)), "application/json")
    row.plan_sha256 = plan.plan_sha256
    row.plan_key = plan_key
    row.status = _review_status(session, row)


def import_source(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    business_id: uuid.UUID,
    user: User,
    filename: str,
    data: bytes,
    artifact_storage: PrivateArtifactStorage,
) -> SourceImport:
    """Validate, snapshot and inspect an uploaded export. An archive the
    source policy refuses (not a ZIP, too large, path traversal, symlinks,
    special files, too many/large entries, no single package.json) is
    rejected with nothing stored."""
    if len(data) > settings.supervised_source_max_bytes:
        raise SourceImportError(
            "The archive is larger than the import limit.", code="source_too_large", status_code=413
        )
    if not data.startswith(b"PK\x03\x04") or not zipfile.is_zipfile(io.BytesIO(data)):
        raise SourceImportError("The upload is not a ZIP archive.", code="source_not_zip", status_code=422)
    api_base_url = resolve_public_api_base_url()
    if public_origin_problem(api_base_url) is not None:
        raise SourceImportError(
            "The public API origin is not configured, so a site cannot be built.",
            code="public_api_origin_unconfigured",
            status_code=409,
        )
    zip_sha = sha256_hex(data)
    row = SourceImport(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        business_id=business_id,
        created_by_user_id=user.id,
        status=SourceImportStatus.BLOCKED,
        original_filename=(Path(filename).name or "export.zip")[:255],
        zip_sha256=zip_sha,
        zip_size=len(data),
        snapshot_key=snapshot_storage_key(tenant_id=tenant_id, business_id=business_id, zip_sha256=zip_sha),
        site_origin=site_origin_for(session, tenant_id=tenant_id, business_id=business_id),
        api_base_url=api_base_url,
        inspection={},
    )
    _inspect_into(session, row, data=data, artifact_storage=artifact_storage)  # validates before the snapshot is stored
    _save_once(artifact_storage, row.snapshot_key, data, "application/zip")
    session.add(row)
    session.flush()
    logger.info(
        "source import business=%s import=%s user=%s status=%s zip=%s plan=%s",
        business_id,
        row.id,
        user.id,
        row.status.value,
        zip_sha[:12],
        (row.plan_sha256 or "-")[:12],
    )
    return row


def load_snapshot(row: SourceImport, artifact_storage: PrivateArtifactStorage) -> bytes:
    data = artifact_storage.load(row.snapshot_key)
    if sha256_hex(data) != row.zip_sha256:
        raise SourceImportError(
            "The stored source snapshot failed its integrity check; nothing was built.",
            code="source_snapshot_integrity",
            status_code=409,
        )
    return data


def load_plan(row: SourceImport, artifact_storage: PrivateArtifactStorage) -> AdaptationPlan:
    if row.plan_key is None or row.plan_sha256 is None:
        raise SourceImportError("This import has no adaptation plan.", code="source_plan_missing", status_code=409)
    try:
        plan = AdaptationPlan.from_dict(json.loads(artifact_storage.load(row.plan_key)))
    except (AdapterError, ValueError, TypeError, KeyError) as exc:
        raise SourceImportError(
            "The stored adaptation plan is unreadable.", code="source_plan_integrity", status_code=409
        ) from exc
    if (
        plan.plan_sha256 != row.plan_sha256
        or plan.snapshot_zip_sha256 != row.zip_sha256
        or plan.business_truth_sha256 != row.business_truth_sha256
    ):
        raise SourceImportError(
            "The stored adaptation plan does not match this import; nothing was built.",
            code="source_plan_integrity",
            status_code=409,
        )
    return plan


def reinspect(session: Session, *, row: SourceImport, artifact_storage: PrivateArtifactStorage) -> SourceImport:
    """Re-plans the same immutable snapshot against the CURRENT BusinessTruth.
    A changed truth produces a new plan identity; decisions made for the old
    plan never apply to it."""
    if row.status not in _REINSPECTABLE:
        raise SourceImportError(
            f"This import can't be re-inspected now (status: {row.status.value}).",
            code="source_import_not_reinspectable",
            status_code=409,
        )
    _inspect_into(session, row, data=load_snapshot(row, artifact_storage), artifact_storage=artifact_storage)
    return row


# --- Review --------------------------------------------------------------------------------


def _pending_review_ids(row: SourceImport) -> list[str]:
    return [f["id"] for f in row.inspection.get("findings", []) if f.get("severity") == "review" and f.get("open")]


def decisions_for_plan(session: Session, row: SourceImport) -> list[SourceReviewDecision]:
    """Decisions bound to THIS import's current snapshot and plan only."""
    if row.plan_sha256 is None:
        return []
    return list(
        session.scalars(
            select(SourceReviewDecision)
            .where(
                SourceReviewDecision.tenant_id == row.tenant_id,
                SourceReviewDecision.source_import_id == row.id,
                SourceReviewDecision.snapshot_sha256 == row.zip_sha256,
                SourceReviewDecision.plan_sha256 == row.plan_sha256,
            )
            .order_by(SourceReviewDecision.created_at, SourceReviewDecision.id)
        ).all()
    )


def _latest_decisions(session: Session, row: SourceImport) -> dict[str, ReviewDecisionKind]:
    return {d.finding_id: d.decision for d in decisions_for_plan(session, row)}


def open_reviews(session: Session, row: SourceImport) -> list[str]:
    """Pending review findings with no approval for this exact snapshot+plan."""
    latest = _latest_decisions(session, row)
    return [fid for fid in _pending_review_ids(row) if latest.get(fid) is not ReviewDecisionKind.APPROVED]


def _review_status(session: Session, row: SourceImport) -> SourceImportStatus:
    latest = _latest_decisions(session, row)
    pending = _pending_review_ids(row)
    if any(latest.get(fid) is ReviewDecisionKind.REJECTED for fid in pending):
        return SourceImportStatus.REJECTED
    if any(latest.get(fid) is not ReviewDecisionKind.APPROVED for fid in pending):
        return SourceImportStatus.NEEDS_REVIEW
    return SourceImportStatus.READY_TO_BUILD


def record_decision(
    session: Session,
    *,
    row: SourceImport,
    finding_id: str,
    decision: ReviewDecisionKind,
    rationale: str,
    user: User,
) -> SourceReviewDecision:
    if refresh_staleness(session, row):
        raise SourceImportError(
            "BusinessTruth changed since this plan was made. Re-inspect before reviewing.",
            code="source_import_stale",
            status_code=409,
        )
    if row.status is not SourceImportStatus.NEEDS_REVIEW:
        raise SourceImportError(
            f"Review decisions are only taken while the import needs review (status: {row.status.value}).",
            code="source_import_not_in_review",
            status_code=409,
        )
    finding = next((f for f in row.inspection.get("findings", []) if f.get("id") == finding_id), None)
    if finding is None:
        raise SourceImportError(
            "That finding is not part of this import's plan.", code="finding_not_found", status_code=404
        )
    if finding.get("severity") == "blocker":
        raise SourceImportError(
            "Blocker findings can never be approved; fix the source or BusinessTruth and import again.",
            code="blocker_not_approvable",
            status_code=409,
        )
    if finding_id not in _pending_review_ids(row):
        raise SourceImportError("That finding does not need a decision.", code="finding_not_pending", status_code=409)
    text = rationale.strip()
    if not text or len(text) > MAX_RATIONALE_CHARS:
        raise SourceImportError(
            f"A rationale (1-{MAX_RATIONALE_CHARS} characters) is required.", code="rationale_required", status_code=422
        )
    assert row.plan_sha256 is not None  # a pending finding implies a proposed plan
    record = SourceReviewDecision(
        tenant_id=row.tenant_id,
        source_import_id=row.id,
        finding_id=finding_id,
        decision=decision,
        rationale=text,
        actor_user_id=user.id,
        actor_email=user.email,
        snapshot_sha256=row.zip_sha256,
        plan_sha256=row.plan_sha256,
    )
    session.add(record)
    session.flush()
    row.status = _review_status(session, row)
    session.flush()
    logger.info(
        "source review decision import=%s finding=%s decision=%s user=%s plan=%s",
        row.id,
        finding_id,
        decision.value,
        user.id,
        row.plan_sha256[:12],
    )
    return record


def refresh_staleness(session: Session, row: SourceImport) -> bool:
    """True (and STALE) when BusinessTruth changed since the plan was made:
    the plan and every decision bound to it no longer authorize a build."""
    if row.status is SourceImportStatus.STALE:
        return True
    if row.status not in _TRUTH_SENSITIVE or row.business_truth_sha256 is None:
        return False
    try:
        _, truth = load_business_inputs(session, tenant_id=row.tenant_id, business_id=row.business_id)
        changed = business_truth_sha256(truth) != row.business_truth_sha256
    except BusinessInputsError:
        changed = True
    if changed:
        row.status = SourceImportStatus.STALE
        logger.info("source import stale import=%s (BusinessTruth changed)", row.id)
    return changed


# --- Build ---------------------------------------------------------------------------------


def worker_configured() -> bool:
    return bool(settings.generation_worker_token_sha256 and settings.generation_worker_signing_key)


def start_build(
    session: Session, *, row: SourceImport, user: User, artifact_storage: PrivateArtifactStorage
) -> GenerationJob:
    """Queue the supervised build on the execution host. Every identity is
    re-verified first; the API never builds the site itself."""
    if refresh_staleness(session, row):
        raise SourceImportError(
            "BusinessTruth changed since this plan was made. Re-inspect the import "
            "(earlier approvals do not carry over).",
            code="source_import_stale",
            status_code=409,
        )
    if row.status not in _BUILDABLE:
        raise SourceImportError(
            f"This import can't be built now (status: {row.status.value}).",
            code="source_import_not_buildable",
            status_code=409,
        )
    if open_reviews(session, row) or _review_status(session, row) is not SourceImportStatus.READY_TO_BUILD:
        raise SourceImportError(
            "Every review finding needs an approval for this exact plan before building.",
            code="source_review_incomplete",
            status_code=409,
        )
    if not worker_configured():
        raise SourceImportError(
            "No build worker is configured on this server; the API never builds imported sites itself.",
            code="build_worker_not_configured",
            status_code=503,
        )
    load_snapshot(row, artifact_storage)
    plan = load_plan(row, artifact_storage)
    attempt = (
        session.scalar(
            select(func.count())
            .select_from(GenerationJob)
            .where(GenerationJob.tenant_id == row.tenant_id, GenerationJob.plan_sha256 == plan.plan_sha256)
        )
        or 0
    )
    draft = WebsiteDraft(
        id=uuid.uuid4(),
        tenant_id=row.tenant_id,
        business_id=row.business_id,
        engine=GenerationEngine.GENERATIVE,
        site_config=None,
        status=WebsiteDraftStatus.BUILDING,
    )
    session.add(draft)
    session.flush()
    steps = " && ".join(" ".join(step["argv"]) for step in plan.build["sandbox_steps"])
    session.add(
        GenerativeWebsiteArtifact(
            tenant_id=row.tenant_id,
            business_id=row.business_id,
            website_draft_id=draft.id,
            framework=str(plan.adapter.get("family", "external"))[:50],
            workspace_key=row.snapshot_key[:300],
            build_command=steps[:300],
            output_dir=str(plan.build["output_dir"])[:300],
            dependencies=[],
            platform_contract_version=PLATFORM_CONTRACT_VERSION,
            qa_state={},
            generator_provider="supervised-import",
            generator_model=f"{row.adapter_id}@{row.adapter_version}"[:100],
            generated_at=datetime.now(UTC),
        )
    )
    job = jobs.submit_job(
        session,
        tenant_id=row.tenant_id,
        business_id=row.business_id,
        idempotency_key=f"source-import:{row.id}:{plan.plan_sha256[:32]}:{attempt}",
        input_sha256=plan.plan_sha256,
        draft_id=draft.id,
        source_key=row.snapshot_key,
        source_sha256=row.zip_sha256,
        api_base_url=row.api_base_url,
        source_family=str(row.source_family),
        job_kind=GenerationJobKind.SOURCE_ADAPTATION,
        trust_class=JobTrustClass.SUPERVISED_SOURCE,
        plan_sha256=plan.plan_sha256,
    )
    row.job_id = job.id
    row.draft_id = draft.id
    row.status = SourceImportStatus.BUILDING
    row.error = None
    session.flush()
    session.flush()
    logger.info(
        "source import build queued import=%s job=%s user=%s plan=%s", row.id, job.id, user.id, plan.plan_sha256[:12]
    )
    return job


def import_for_job(session: Session, job: GenerationJob) -> SourceImport | None:
    return session.scalar(
        select(SourceImport).where(SourceImport.tenant_id == job.tenant_id, SourceImport.job_id == job.id)
    )


def import_for_draft(session: Session, draft: WebsiteDraft) -> SourceImport | None:
    return session.scalar(
        select(SourceImport).where(SourceImport.tenant_id == draft.tenant_id, SourceImport.draft_id == draft.id)
    )


def sync_from_job(session: Session, row: SourceImport) -> None:
    """Reflect a finished job on its import (called by trusted intake)."""
    if row.job_id is None or row.status is not SourceImportStatus.BUILDING:
        return
    job = session.get(GenerationJob, row.job_id)
    if job is None:
        return
    if job.status is GenerationJobStatus.SUCCEEDED:
        row.status = SourceImportStatus.PREVIEW_READY
    elif job.status is GenerationJobStatus.FAILED:
        row.status = SourceImportStatus.BUILD_FAILED
        draft = session.get(WebsiteDraft, row.draft_id) if row.draft_id else None
        kind = job.failure_kind.value if job.failure_kind else "failed"
        row.error = (draft.build_error if draft and draft.build_error else None) or f"The build was refused ({kind})."


# --- Approval / publish gate -------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactGate:
    ok: bool
    problems: tuple[str, ...]


def artifact_gate(session: Session, draft: WebsiteDraft) -> ArtifactGate:
    """For a draft built from a supervised import: may THIS exact artifact
    be approved or published? (Other drafts: not this gate's concern.)"""
    row = import_for_draft(session, draft)
    if row is None:
        return ArtifactGate(True, ())
    problems: list[str] = []
    try:
        _, truth = load_business_inputs(session, tenant_id=draft.tenant_id, business_id=draft.business_id)
        if business_truth_sha256(truth) != row.business_truth_sha256:
            problems.append("BusinessTruth changed since this site was built; re-inspect and rebuild the import.")
    except BusinessInputsError:
        problems.append("The business has no usable configuration.")
    artifact_row = session.scalar(
        select(GenerativeWebsiteArtifact).where(
            GenerativeWebsiteArtifact.tenant_id == draft.tenant_id,
            GenerativeWebsiteArtifact.website_draft_id == draft.id,
        )
    )
    state = artifact_row.visual_qa_state if artifact_row is not None else None
    if not evidence_is_current(state, draft.artifact_sha256):
        problems.append("Visual QA has not been run for this exact artifact (or is stale); run it before approving.")
    elif not (state or {}).get("passed"):
        problems.append("Visual QA failed for this artifact; it can't be approved.")
    return ArtifactGate(not problems, tuple(problems))
