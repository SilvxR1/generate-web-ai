"""R5 — supervised source imports (operator API).

    GET  /businesses/{id}/source-imports/capability
    POST /businesses/{id}/source-imports                    (multipart ZIP)
    GET  /businesses/{id}/source-imports
    GET  /businesses/{id}/source-imports/{import_id}
    GET  /businesses/{id}/source-imports/{import_id}/diagnostics
    POST /businesses/{id}/source-imports/{import_id}/decisions
    POST /businesses/{id}/source-imports/{import_id}/reinspect
    POST /businesses/{id}/source-imports/{import_id}/build

Preview, approve, publish and rollback reuse the existing website-draft and
website-version routes (the import's `draft_id`), which enforce the R5
artifact gate. Everything here requires an authenticated tenant member and
the `supervised_source_imports_enabled` server setting (off by default).
"""

import json
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.creative import source_imports as imports
from app.creative.business_inputs import BusinessInputsError, business_truth_sha256, load_business_inputs
from app.db.models.generation_job import GenerationJob
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.source_import import SourceImport
from app.db.models.user import User
from app.db.models.website_draft import WebsiteDraft
from app.dependencies import get_current_tenant_id, get_current_user, get_private_artifact_storage, get_session
from app.domain.enums import GenerationJobStatus, ReviewDecisionKind, SourceImportStatus, WebsiteDraftStatus
from app.errors import AppError
from app.publishing.public_origin import public_origin_problem, resolve_public_api_base_url
from app.publishing.qa_evidence import evidence_is_current
from app.services.business_service import BusinessNotFoundError, BusinessService
from app.storage.private import PrivateArtifactStorage

router = APIRouter(prefix="/businesses/{business_id}/source-imports", tags=["source-imports"])


# --- Schemas ---------------------------------------------------------------------------


class SourceImportCapability(BaseModel):
    enabled: bool
    # R5.1.1: "global" (feature flag), "scoped" (THIS business is allowlisted
    # for a supervised canary while the flag is off) or "disabled". The
    # allowlist itself is never returned.
    access: Literal["global", "scoped", "disabled"]
    worker_configured: bool
    max_bytes: int
    api_base_url_configured: bool
    site_origin: str | None
    supervised_only: bool = True


class ReviewDecisionRead(BaseModel):
    finding_id: str
    decision: ReviewDecisionKind
    rationale: str
    actor_email: str
    snapshot_sha256: str
    plan_sha256: str
    created_at: datetime


class DraftStateRead(BaseModel):
    id: uuid.UUID
    status: WebsiteDraftStatus
    artifact_sha256: str | None
    approved_artifact_sha256: str | None
    build_error: str | None
    preview_url: str | None
    visual_qa_current: bool
    visual_qa_passed: bool | None
    gate_problems: list[str]


class SourceImportSummary(BaseModel):
    id: uuid.UUID
    status: SourceImportStatus
    stage: str
    original_filename: str
    zip_sha256: str
    zip_size: int
    source_family: str | None
    adapter: str | None
    supportability: str | None
    plan_sha256: str | None
    created_at: datetime


class SourceImportRead(SourceImportSummary):
    manifest_sha256: str | None
    business_truth_sha256: str | None
    business_truth_current: bool
    site_origin: str
    api_base_url: str
    inspection: dict
    open_reviews: list[str]
    decisions: list[ReviewDecisionRead]
    job_status: str | None
    job_failure: str | None
    error: str | None
    draft: DraftStateRead | None


class DecisionRequest(BaseModel):
    finding_id: str = Field(min_length=1, max_length=400)
    decision: Literal["approved", "rejected"]
    rationale: str = Field(min_length=1, max_length=imports.MAX_RATIONALE_CHARS)


# --- Helpers ----------------------------------------------------------------------------


def require_supervised_import_access(
    business_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> uuid.UUID:
    """THE gate of every supervised-import lifecycle route (R5.1.1).

    1. authentication + tenant authorization: `get_current_tenant_id` (the
       session cookie and a TenantAccess grant for X-Tenant-Id) — unchanged;
    2. feature availability for THIS path business: the global flag, or the
       business explicitly allowlisted (scoped canary) — else 403;
    3. the business belongs to the caller's tenant — else 404.
    Returns the authorized tenant id. Routes then load rows filtered by
    BOTH tenant and this business id, so an import of another business can
    never be reached through an allowlisted business's path."""
    if imports.supervised_import_access(business_id) == "disabled":
        raise AppError("This feature is not available.", code="feature_not_available", status_code=403)
    _business(session, tenant_id, business_id)
    return tenant_id


def _business(session: Session, tenant_id: uuid.UUID, business_id: uuid.UUID) -> None:
    try:
        BusinessService(session).get(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise AppError("Business not found.", code="business_not_found", status_code=404) from exc


def _row(session: Session, tenant_id: uuid.UUID, business_id: uuid.UUID, import_id: uuid.UUID) -> SourceImport:
    row = session.scalar(
        select(SourceImport).where(
            SourceImport.tenant_id == tenant_id, SourceImport.business_id == business_id, SourceImport.id == import_id
        )
    )
    if row is None:
        raise AppError("Source import not found.", code="source_import_not_found", status_code=404)
    return row


def _error(exc: imports.SourceImportError) -> AppError:
    return AppError(str(exc), code=exc.code, status_code=exc.status_code)


def _stage(row: SourceImport, job: GenerationJob | None, draft: WebsiteDraft | None) -> str:
    """The operator-facing lifecycle stage (one word, never ambiguous)."""
    if row.status is SourceImportStatus.BUILDING:
        return "queued" if job is not None and job.status is GenerationJobStatus.QUEUED else "building"
    if row.status is SourceImportStatus.PREVIEW_READY and draft is not None:
        return {
            WebsiteDraftStatus.READY: "preview_ready",
            WebsiteDraftStatus.APPROVED: "approved",
            WebsiteDraftStatus.PUBLISHED: "published",
        }.get(draft.status, draft.status.value)
    return row.status.value


def _summary(row: SourceImport, stage: str) -> dict:
    return {
        "id": row.id,
        "status": row.status,
        "stage": stage,
        "original_filename": row.original_filename,
        "zip_sha256": row.zip_sha256,
        "zip_size": row.zip_size,
        "source_family": row.source_family,
        "adapter": f"{row.adapter_id}@{row.adapter_version}" if row.adapter_id else None,
        "supportability": row.supportability,
        "plan_sha256": row.plan_sha256,
        "created_at": row.created_at,
    }


def _draft_state(session: Session, draft: WebsiteDraft) -> DraftStateRead:
    artifact_row = session.scalar(
        select(GenerativeWebsiteArtifact).where(
            GenerativeWebsiteArtifact.tenant_id == draft.tenant_id,
            GenerativeWebsiteArtifact.website_draft_id == draft.id,
        )
    )
    state = artifact_row.visual_qa_state if artifact_row is not None else {}
    current = evidence_is_current(state, draft.artifact_sha256)
    gated = draft.status in (WebsiteDraftStatus.READY, WebsiteDraftStatus.APPROVED)
    gate = imports.artifact_gate(session, draft) if gated else None
    return DraftStateRead(
        id=draft.id,
        status=draft.status,
        artifact_sha256=draft.artifact_sha256,
        approved_artifact_sha256=draft.approved_artifact_sha256,
        build_error=draft.build_error,
        preview_url=draft.preview_url,
        visual_qa_current=current,
        visual_qa_passed=bool(state.get("passed")) if current else None,
        gate_problems=list(gate.problems) if gate is not None else [],
    )


def _refresh(session: Session, row: SourceImport) -> tuple[GenerationJob | None, WebsiteDraft | None]:
    imports.refresh_staleness(session, row)
    job = session.get(GenerationJob, row.job_id) if row.job_id else None
    if job is not None:
        imports.sync_from_job(session, row)
    draft = session.get(WebsiteDraft, row.draft_id) if row.draft_id else None
    return job, draft


def _read(session: Session, row: SourceImport) -> SourceImportRead:
    job, draft = _refresh(session, row)
    try:
        _, truth = load_business_inputs(session, tenant_id=row.tenant_id, business_id=row.business_id)
        truth_current = business_truth_sha256(truth) == row.business_truth_sha256
    except BusinessInputsError:
        truth_current = False
    decisions = [
        ReviewDecisionRead(
            finding_id=d.finding_id,
            decision=d.decision,
            rationale=d.rationale,
            actor_email=d.actor_email,
            snapshot_sha256=d.snapshot_sha256,
            plan_sha256=d.plan_sha256,
            created_at=d.created_at,
        )
        for d in imports.decisions_for_plan(session, row)
    ]
    return SourceImportRead(
        **_summary(row, _stage(row, job, draft)),
        manifest_sha256=row.manifest_sha256,
        business_truth_sha256=row.business_truth_sha256,
        business_truth_current=truth_current,
        site_origin=row.site_origin,
        api_base_url=row.api_base_url,
        inspection=row.inspection,
        open_reviews=imports.open_reviews(session, row),
        decisions=decisions,
        job_status=job.status.value if job else None,
        job_failure=job.failure_kind.value if job and job.failure_kind else None,
        error=row.error,
        draft=_draft_state(session, draft) if draft is not None else None,
    )


# --- Routes ----------------------------------------------------------------------------


@router.get("/capability", response_model=SourceImportCapability)
def capability(
    business_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> SourceImportCapability:
    _business(session, tenant_id, business_id)
    access = imports.supervised_import_access(business_id)
    return SourceImportCapability(
        enabled=access != "disabled",
        access=access,
        worker_configured=imports.worker_configured(),
        max_bytes=settings.supervised_source_max_bytes,
        api_base_url_configured=public_origin_problem(resolve_public_api_base_url()) is None,
        site_origin=imports.site_origin_for(session, tenant_id=tenant_id, business_id=business_id),
    )


# Multipart overhead allowed on top of the archive limit (boundaries, part headers).
_MULTIPART_SLACK_BYTES = 1024 * 1024
_UPLOAD_PATH = re.compile(r"^/businesses/[^/]+/source-imports/?$")


class SourceUploadLimitMiddleware:
    """R5.1: refuse an oversized supervised upload from its Content-Length,
    BEFORE the body is received. Starlette spools the whole multipart body
    to disk before the route's own check runs, so without this a client
    could stream far more than the limit into the API's temp storage. The
    route's exact check (`supervised_source_max_bytes`) stays authoritative
    for bodies without a Content-Length (chunked)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and _UPLOAD_PATH.match(scope["path"]):
            length = dict(scope["headers"]).get(b"content-length", b"")
            limit = settings.supervised_source_max_bytes + _MULTIPART_SLACK_BYTES
            if length.isdigit() and int(length) > limit:
                body = {
                    "error": {"code": "source_too_large", "message": "The archive is larger than the import limit."}
                }
                await JSONResponse(body, status_code=413, headers={"Connection": "close"})(scope, receive, send)
                return
        await self.app(scope, receive, send)


@router.post("", response_model=SourceImportRead, status_code=status.HTTP_201_CREATED)
async def create_source_import(
    business_id: uuid.UUID,
    file: UploadFile = File(...),
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
) -> SourceImportRead:
    data = await file.read(settings.supervised_source_max_bytes + 1)
    try:
        row = imports.import_source(
            session,
            tenant_id=tenant_id,
            business_id=business_id,
            user=user,
            filename=file.filename or "export.zip",
            data=data,
            artifact_storage=artifact_storage,
        )
    except imports.SourceImportError as exc:
        raise _error(exc) from exc
    return _read(session, row)


@router.get("", response_model=list[SourceImportSummary])
def list_source_imports(
    business_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    session: Session = Depends(get_session),
) -> list[SourceImportSummary]:
    rows = session.scalars(
        select(SourceImport)
        .where(SourceImport.tenant_id == tenant_id, SourceImport.business_id == business_id)
        .order_by(SourceImport.created_at.desc(), SourceImport.id)
    ).all()
    out = []
    for row in rows:
        job, draft = _refresh(session, row)
        out.append(SourceImportSummary(**_summary(row, _stage(row, job, draft))))
    return out


@router.get("/{import_id}", response_model=SourceImportRead)
def get_source_import(
    business_id: uuid.UUID,
    import_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    session: Session = Depends(get_session),
) -> SourceImportRead:
    return _read(session, _row(session, tenant_id, business_id, import_id))


@router.get("/{import_id}/diagnostics")
def source_import_diagnostics(
    business_id: uuid.UUID,
    import_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
) -> dict:
    """Secondary diagnostic view: the raw SourceManifest and plan (binary
    operation content summarized by its SHA-256)."""
    row = _row(session, tenant_id, business_id, import_id)
    manifest = json.loads(artifact_storage.load(row.manifest_key)) if row.manifest_key else None
    plan = None
    if row.plan_key:
        try:
            plan = imports.load_plan(row, artifact_storage).to_dict()
        except imports.SourceImportError as exc:
            raise _error(exc) from exc
    return {"manifest": manifest, "plan": plan, "plan_sha256": row.plan_sha256}


@router.post("/{import_id}/decisions", response_model=SourceImportRead)
def decide(
    business_id: uuid.UUID,
    import_id: uuid.UUID,
    body: DecisionRequest,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SourceImportRead:
    row = _row(session, tenant_id, business_id, import_id)
    try:
        imports.record_decision(
            session,
            row=row,
            finding_id=body.finding_id,
            decision=ReviewDecisionKind(body.decision),
            rationale=body.rationale,
            user=user,
        )
    except imports.SourceImportError as exc:
        session.commit()  # a STALE transition is kept even when the decision is refused
        raise _error(exc) from exc
    return _read(session, row)


@router.post("/{import_id}/reinspect", response_model=SourceImportRead)
def reinspect(
    business_id: uuid.UUID,
    import_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
) -> SourceImportRead:
    row = _row(session, tenant_id, business_id, import_id)
    try:
        imports.reinspect(session, row=row, artifact_storage=artifact_storage)
    except imports.SourceImportError as exc:
        raise _error(exc) from exc
    return _read(session, row)


@router.post("/{import_id}/build", response_model=SourceImportRead, status_code=status.HTTP_202_ACCEPTED)
def build(
    business_id: uuid.UUID,
    import_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(require_supervised_import_access),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
) -> SourceImportRead:
    row = _row(session, tenant_id, business_id, import_id)
    try:
        imports.start_build(session, row=row, user=user, artifact_storage=artifact_storage)
    except imports.SourceImportError as exc:
        session.commit()  # keep a STALE transition
        raise _error(exc) from exc
    return _read(session, row)
