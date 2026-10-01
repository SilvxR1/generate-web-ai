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
- Conservative retries: NONE automatic for generative jobs. A job may
  already have made a paid provider call, and contract/drift/build
  failures are deterministic, so every failure is terminal. A worker that
  disappears leaves an expired lease; `expire_lost_jobs` marks it
  FAILED(worker_lost) — it is not re-run. A deliberate retry is a new job
  with a new key.
- R5.1 exception: a SOURCE_ADAPTATION job (a supervised export: no
  provider call, no cost, deterministic input) whose worker was LOST
  (crash, restart, SIGTERM) goes back to QUEUED — `requeue_lost` — up to
  MAX_SOURCE_ATTEMPTS claims. Each claim is a new attempt with a new job
  token, so a late result from the lost attempt is refused (token and
  attempt no longer match) and can never create a second artifact.
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
from app.domain.enums import GenerationFailureKind, GenerationJobKind, GenerationJobStatus, JobTrustClass
from app.publishing.csp_policy import DEFAULT_SOURCE_FAMILY, parse_family

DEFAULT_LEASE = timedelta(minutes=15)
MAX_SOURCE_ATTEMPTS = 3
_MAX_ERROR_CHARS = 2000

TRANSITIONS: dict[GenerationJobStatus, frozenset[GenerationJobStatus]] = {
    GenerationJobStatus.QUEUED: frozenset({GenerationJobStatus.RUNNING, GenerationJobStatus.FAILED}),
    # RUNNING -> QUEUED only through requeue_lost (source-adaptation jobs).
    GenerationJobStatus.RUNNING: frozenset(
        {GenerationJobStatus.SUCCEEDED, GenerationJobStatus.FAILED, GenerationJobStatus.QUEUED}
    ),
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
    draft_id: uuid.UUID | None = None,
    source_key: str | None = None,
    source_sha256: str | None = None,
    api_base_url: str | None = None,
    source_family: str = DEFAULT_SOURCE_FAMILY,
    job_kind: GenerationJobKind = GenerationJobKind.GENERATIVE,
    trust_class: JobTrustClass = JobTrustClass.UNTRUSTED_GENERATED,
    plan_sha256: str | None = None,
) -> GenerationJob:
    # H1.1: fail closed before anything is stored — an unknown family has no
    # CSP policy (raises UnsupportedCspRequirementError).
    family = parse_family(source_family)
    # R5: AI-generated code is never downgraded to the supervised tier.
    if job_kind is GenerationJobKind.GENERATIVE and trust_class is not JobTrustClass.UNTRUSTED_GENERATED:
        raise GenerationJobError("a generative job always requires the untrusted (sandboxed) trust class")
    existing = session.scalar(
        select(GenerationJob).where(
            GenerationJob.tenant_id == tenant_id, GenerationJob.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.business_id != business_id
            or existing.input_sha256 != input_sha256
            or existing.source_family != family.value
            or existing.job_kind is not job_kind
            or existing.trust_class is not trust_class
            or existing.plan_sha256 != plan_sha256
        ):
            raise GenerationJobError("idempotency key already used for a different generation request")
        return existing
    job = GenerationJob(
        tenant_id=tenant_id,
        business_id=business_id,
        idempotency_key=idempotency_key,
        input_sha256=input_sha256,
        status=GenerationJobStatus.QUEUED,
        attempts=0,
        draft_id=draft_id,
        source_key=source_key,
        source_sha256=source_sha256,
        api_base_url=api_base_url,
        source_family=family.value,
        job_kind=job_kind,
        trust_class=trust_class,
        plan_sha256=plan_sha256,
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


def next_queued_job_id(
    session: Session, *, trust_classes: frozenset[JobTrustClass] | None = None
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(tenant_id, job_id) of the oldest QUEUED job with a build input —
    for the platform-level execution host, which serves every tenant but
    only ever receives one job's own input at a time. R5: `trust_classes`
    limits the jobs to those the claiming worker's isolation may run."""
    query = select(GenerationJob.tenant_id, GenerationJob.id).where(
        GenerationJob.status == GenerationJobStatus.QUEUED, GenerationJob.source_key.is_not(None)
    )
    if trust_classes is not None:
        query = query.where(GenerationJob.trust_class.in_(sorted(trust_classes)))
    row = session.execute(query.order_by(GenerationJob.created_at, GenerationJob.id).limit(1)).first()
    return None if row is None else (row[0], row[1])


def succeed(job: GenerationJob, *, draft_id: uuid.UUID | None = None) -> None:
    _transition(job, GenerationJobStatus.SUCCEEDED)
    job.draft_id = draft_id or job.draft_id
    job.lease_expires_at = None
    job.finished_at = _now()


def fail(job: GenerationJob, *, kind: GenerationFailureKind, error: str) -> None:
    """Terminal — see the module docstring on why nothing is retried."""
    _transition(job, GenerationJobStatus.FAILED)
    job.failure_kind = kind
    job.error = error[:_MAX_ERROR_CHARS]
    job.lease_expires_at = None
    job.finished_at = _now()


def requeue_lost(job: GenerationJob, *, reason: str) -> bool:
    """R5.1: a lost SOURCE_ADAPTATION attempt goes back to the queue while
    attempts remain (True); anything else is not this function's to retry."""
    if job.job_kind is not GenerationJobKind.SOURCE_ADAPTATION or job.attempts >= MAX_SOURCE_ATTEMPTS:
        return False
    _transition(job, GenerationJobStatus.QUEUED)
    job.lease_expires_at = None
    job.error = f"attempt {job.attempts} lost ({reason[:200]}); requeued"
    return True


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
