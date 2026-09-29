"""v0.2 R4.1 — the two internal endpoints an isolated execution host uses.

    POST /internal/generation-worker/claim                  (worker credential)
    POST /internal/generation-worker/jobs/{job_id}/result   (job token)

Dormant unless BOTH generation_worker_token_sha256 and
generation_worker_signing_key are configured (404 otherwise). The host
pulls work over HTTPS, so it needs no inbound port, no database URL and
no storage credential; see app.worker.auth for what each credential can
and cannot do.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.generation_job import GenerationJob
from app.dependencies import get_private_artifact_storage, get_session, get_storage_provider
from app.storage import StorageProvider
from app.storage.private import PrivateArtifactStorage
from app.worker import intake
from app.worker.auth import WorkerAuthError, verify_job_token, verify_worker_token
from app.worker.protocol import ExecutionResult

router = APIRouter(prefix="/internal/generation-worker", tags=["internal"], include_in_schema=False)


def _configured() -> tuple[str, str]:
    token_hash, signing_key = settings.generation_worker_token_sha256, settings.generation_worker_signing_key
    if not token_hash or not signing_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return token_hash, signing_key


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None


@router.post("/claim")
def claim_job(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
    asset_storage: StorageProvider = Depends(get_storage_provider),
) -> object:
    token_hash, signing_key = _configured()
    try:
        verify_worker_token(_bearer(authorization), expected_sha256=token_hash)
    except WorkerAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
    claimed = intake.claim_next(
        session, artifact_storage=artifact_storage, asset_storage=asset_storage, signing_key=signing_key
    )
    if claimed is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    request, job_token = claimed
    return {"request": request.model_dump(mode="json"), "job_token": job_token}


@router.post("/jobs/{job_id}/result", status_code=status.HTTP_204_NO_CONTENT)
def submit_result(
    job_id: uuid.UUID,
    result: ExecutionResult,
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
    artifact_storage: PrivateArtifactStorage = Depends(get_private_artifact_storage),
    asset_storage: StorageProvider = Depends(get_storage_provider),
) -> Response:
    _, signing_key = _configured()
    job = session.scalar(select(GenerationJob).where(GenerationJob.id == job_id))
    try:
        if job is None:
            raise WorkerAuthError("unknown job")
        verify_job_token(_bearer(authorization), job_id=job.id, attempt=job.attempts, signing_key=signing_key)
    except WorkerAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED) from exc
    assert job is not None
    try:
        business_config, business_truth = intake.load_job_inputs(session, job)
        intake.accept_result(
            session,
            job=job,
            result=result,
            business_config=business_config,
            business_truth=business_truth,
            artifact_storage=artifact_storage,
            asset_storage=asset_storage,
        )
    except intake.IntakeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
