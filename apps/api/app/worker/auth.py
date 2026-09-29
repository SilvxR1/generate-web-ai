"""v0.2 R4.1 — narrow credentials between the control plane and the
execution host. Neither is any existing platform secret.

- Worker credential (claim scope only): the host holds a random token;
  the API stores only its SHA-256 (`generation_worker_token_sha256`). It
  can do exactly one thing: claim the next QUEUED job.
- Job token (result scope only): issued per claim, HMAC-signed by the API
  (`generation_worker_signing_key`, which never leaves the API), bound to
  one job id and one attempt, short-lived. It can do exactly one thing:
  submit that attempt's result once.

A leaked worker credential lets an attacker claim (and so fail) queued
jobs; it never reads tenant data beyond a job's own build input, never
reaches the database, storage, Cloudflare, email, n8n or the provider.
"""

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

JOB_TOKEN_TTL = timedelta(minutes=20)
_VERSION = "v1"


class WorkerAuthError(Exception):
    """Credential missing, wrong, expired or for a different job/attempt."""


def hash_worker_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_worker_token(presented: str | None, *, expected_sha256: str | None) -> None:
    if not expected_sha256 or not presented:
        raise WorkerAuthError("worker credential missing")
    if not hmac.compare_digest(hash_worker_token(presented), expected_sha256.lower()):
        raise WorkerAuthError("worker credential invalid")


def _sign(key: str, payload: str) -> str:
    digest = hmac.new(key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_job_token(*, job_id: uuid.UUID, attempt: int, signing_key: str, now: datetime | None = None) -> str:
    expires = int(((now or datetime.now(UTC)) + JOB_TOKEN_TTL).timestamp())
    payload = f"{_VERSION}.{job_id}.{attempt}.{expires}"
    return f"{payload}.{_sign(signing_key, payload)}"


def verify_job_token(
    token: str | None, *, job_id: uuid.UUID, attempt: int, signing_key: str | None, now: datetime | None = None
) -> None:
    if not token or not signing_key:
        raise WorkerAuthError("job token missing")
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != _VERSION:
        raise WorkerAuthError("job token malformed")
    payload = ".".join(parts[:4])
    if not hmac.compare_digest(_sign(signing_key, payload), parts[4]):
        raise WorkerAuthError("job token signature invalid")
    if parts[1] != str(job_id) or parts[2] != str(attempt):
        raise WorkerAuthError("job token is for a different job or attempt")
    if int(parts[3]) < int((now or datetime.now(UTC)).timestamp()):
        raise WorkerAuthError("job token expired")
