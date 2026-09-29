"""v0.2 R4 — generation job orchestration (control plane side).

Explicit state machine over app.db.models.GenerationJob:

    QUEUED --claim--> RUNNING --succeed--> SUCCEEDED
       |                 |
       +-----fail--------+-----fail------> FAILED

- Idempotent submission: (tenant, idempotency_key) maps to exactly one
  job; the same key with a different input is refused, never silently
  re-used for a different request.
- Single claim: `claim` is a conditional UPDATE (status = QUEUED), so two
  workers racing for a job cannot both run it.
- Conservative retries: NONE automatic. A job may already have made a paid
  provider call, and contract/drift/build failures are deterministic, so
  every failure is terminal. A worker that disappears leaves an expired
  lease; `expire_lost_jobs` marks it FAILED(worker_lost) — it is not
  re-run. A deliberate retry is a new job with a new key.
- Tenant-scoped: every read filters by tenant_id.

Not yet wired to the HTTP route: the generative route still runs
synchronously and stays disabled in production (S0 gate) until an
isolated worker host exists (R4 infrastructure decision).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.generation_job import GenerationJob
from app.domain.enums import GenerationFailureKind, GenerationJobStatus

DEFAULT_LEASE = timedelta(minutes=15)
_MAX_ERROR_CHARS = 2000

TRANSITIONS: dict[GenerationJobStatus, frozenset[GenerationJobStatus]] = {
    GenerationJobStatus.QUEUED: frozenset({GenerationJobStatus.RUNNING, GenerationJobStatus.FAILED}),
    GenerationJobStatus.RUNNING: frozenset({GenerationJobStatus.SUCCEEDED, GenerationJobStatus.FAILED}),
    GenerationJobStatus.SUCCEEDED: frozenset(),
    GenerationJobStatus.FAILED: frozenset(),
}


class GenerationJobError(Exception):
    """Illegal transition or conflicting idempotent submission."""


def _now() -> datetime:
    return datetime.now(UTC)


def _transition(job: GenerationJob, target: GenerationJobStatus) -> None:
    if target not in TRANSITIONS[job.status]:
        raise GenerationJobError(f"illegal generation job transition {job.status} -> {target}")
    job.status = target


def get_job(session: Session, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> GenerationJob | None:
    return session.scalar(select(GenerationJob).where(GenerationJob.id == job_id, GenerationJob.tenant_id == tenant_id))


def submit_job(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    business_id: uuid.UUID,
    idempotency_key: str,
    input_sha256: str,
) -> GenerationJob:
    existing = session.scalar(
        select(GenerationJob).where(
            GenerationJob.tenant_id == tenant_id, GenerationJob.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.business_id != business_id or existing.input_sha256 != input_sha256:
            raise GenerationJobError("idempotency key already used for a different generation request")
        return existing
    job = GenerationJob(
        tenant_id=tenant_id,
        business_id=business_id,
        idempotency_key=idempotency_key,
        input_sha256=input_sha256,
        status=GenerationJobStatus.QUEUED,
        attempts=0,
    )
    session.add(job)
    session.flush()
    return job


def claim(
    session: Session, *, tenant_id: uuid.UUID, job_id: uuid.UUID, lease: timedelta = DEFAULT_LEASE
) -> GenerationJob | None:
    """QUEUED -> RUNNING exactly once; None when another worker (or a
    terminal state) got there first."""
    now = _now()
    result = session.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.tenant_id == tenant_id,
            GenerationJob.status == GenerationJobStatus.QUEUED,
        )
        .values(
            status=GenerationJobStatus.RUNNING,
            attempts=GenerationJob.attempts + 1,
            started_at=now,
            lease_expires_at=now + lease,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        return None
    job = get_job(session, tenant_id=tenant_id, job_id=job_id)
    if job is not None:
        session.refresh(job)
    return job


def succeed(job: GenerationJob, *, draft_id: uuid.UUID) -> None:
    _transition(job, GenerationJobStatus.SUCCEEDED)
    job.draft_id = draft_id
    job.lease_expires_at = None
    job.finished_at = _now()


def fail(job: GenerationJob, *, kind: GenerationFailureKind, error: str) -> None:
    """Terminal — see the module docstring on why nothing is retried."""
    _transition(job, GenerationJobStatus.FAILED)
    job.failure_kind = kind
    job.error = error[:_MAX_ERROR_CHARS]
    job.lease_expires_at = None
    job.finished_at = _now()


def expire_lost_jobs(session: Session, *, now: datetime | None = None) -> int:
    """RUNNING jobs whose worker stopped renewing its lease -> FAILED."""
    now = now or _now()
    lost = session.scalars(
        select(GenerationJob).where(
            GenerationJob.status == GenerationJobStatus.RUNNING, GenerationJob.lease_expires_at < now
        )
    ).all()
    for job in lost:
        fail(job, kind=GenerationFailureKind.WORKER_LOST, error="worker lease expired; not retried automatically")
    return len(lost)
