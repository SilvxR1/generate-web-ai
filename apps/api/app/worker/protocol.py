"""v0.2 R4.1 — the job-scoped protocol between the trusted control plane
(Railway API) and an isolated execution host.

The execution host receives ONLY an ExecutionRequest: job identity, the
already-generated SOURCE (the provider call happened trusted-side), the
public API origin the platform config points at, and the business's own
assets as bytes for offline Visual QA. No BusinessConfig, no database
URL, no storage or provider credential.

It returns ONLY an ExecutionResult: status, a candidate archive with its
SHA-256, Visual QA findings/screenshots and safe execution metadata. The
control plane treats every byte of it as untrusted (`unpack_candidate`)
and remains the sole authority for contracts, storage and READY.
"""

import base64
import hashlib
import io
import tarfile
import uuid
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import GenerationFailureKind

PROTOCOL_VERSION: Literal["1"] = "1"
MAX_SOURCE_ARCHIVE_BYTES = 5 * 1024**2
MAX_SOURCE_FILES = 500
MAX_SOURCE_FILE_BYTES = 2 * 1024**2
MAX_CANDIDATE_ARCHIVE_BYTES = 60 * 1024**2
MAX_CANDIDATE_FILES = 2000
MAX_CANDIDATE_FILE_BYTES = 25 * 1024**2
MAX_CANDIDATE_TOTAL_BYTES = 100 * 1024**2
SOURCE_ROOTS = ("src/", "public/")


class ProtocolError(ValueError):
    """A request or result violates the protocol — rejected, never repaired."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str, *, limit: int) -> bytes:
    if len(text) > (limit * 4) // 3 + 8:
        raise ProtocolError("payload exceeds its size limit")
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except ValueError as exc:
        raise ProtocolError("payload is not valid base64") from exc


class ExecutionRequest(BaseModel):
    protocol_version: Literal["1"] = PROTOCOL_VERSION
    job_id: uuid.UUID
    attempt: int
    business_id: uuid.UUID
    api_base_url: str | None = None
    # H1.1: the job's trusted source family (app.publishing.csp_policy); the
    # host builds with exactly this policy so its Visual QA exercises the CSP
    # that trusted intake re-derives and stores.
    source_family: str = Field(default="gwa-astro", max_length=64)
    source_archive: str  # base64 tar.gz: src/ and public/ only
    source_sha256: str = Field(min_length=64, max_length=64)
    offline_assets: dict[str, str] = Field(default_factory=dict)  # url -> base64 bytes
    run_visual_qa: bool = True


class VisualQAReport(BaseModel):
    passed: bool
    findings: list[dict[str, object]] = Field(default_factory=list)
    blocked_requests: list[str] = Field(default_factory=list)
    screenshots: dict[str, str] = Field(default_factory=dict)  # viewport -> base64 PNG


class ExecutionResult(BaseModel):
    protocol_version: Literal["1"] = PROTOCOL_VERSION
    job_id: uuid.UUID
    attempt: int
    status: Literal["succeeded", "failed"]
    failure_kind: GenerationFailureKind | None = None
    error: str | None = Field(default=None, max_length=2000)
    candidate_archive: str | None = None  # base64 tar.gz of the built site
    candidate_sha256: str | None = None
    visual_qa: VisualQAReport | None = None
    metadata: dict[str, object] = Field(default_factory=dict)  # runner, limits enforced, durations


def pack_files(files: dict[str, bytes]) -> bytes:
    """Deterministic tar.gz (sorted, fixed mtime/mode) of regular files."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=6) as tar:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size = len(files[name])
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(files[name]))
    return buffer.getvalue()


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
        raise ProtocolError("archive member has an unsafe path")
    return path.as_posix()


def _unpack(archive: bytes, *, max_archive: int, max_files: int, max_file: int, max_total: int) -> dict[str, bytes]:
    if len(archive) > max_archive:
        raise ProtocolError("archive exceeds its size limit")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar:
                if member.isdir():
                    continue
                if not member.isreg():
                    raise ProtocolError("archive contains a link or special file")
                name = _safe_name(member.name)
                if member.size > max_file:
                    raise ProtocolError("archive member exceeds its size limit")
                total += member.size
                if total > max_total or len(files) >= max_files:
                    raise ProtocolError("archive exceeds its file-count/size limit")
                handle = tar.extractfile(member)
                if handle is None:
                    raise ProtocolError("archive member is unreadable")
                data = handle.read(max_file + 1)
                if len(data) != member.size or name in files:
                    raise ProtocolError("archive member is inconsistent or duplicated")
                files[name] = data
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ProtocolError("archive is not a valid tar.gz") from exc
    return files


def unpack_source(archive: bytes) -> dict[str, bytes]:
    """Generated source only: files under src/ or public/. Engine-owned
    scaffolding (package.json, lockfile, configs) is never accepted from
    the archive — the executor re-authors it."""
    files = _unpack(
        archive,
        max_archive=MAX_SOURCE_ARCHIVE_BYTES,
        max_files=MAX_SOURCE_FILES,
        max_file=MAX_SOURCE_FILE_BYTES,
        max_total=MAX_SOURCE_ARCHIVE_BYTES * 4,
    )
    for name in files:
        if not name.startswith(SOURCE_ROOTS):
            raise ProtocolError("source archive contains a file outside src/ and public/")
    return files


def unpack_candidate(archive: bytes, *, expected_sha256: str) -> dict[str, bytes]:
    """Trusted-side intake of the untrusted candidate: integrity first,
    then bounded, link-free, path-safe extraction."""
    if sha256_hex(archive) != expected_sha256:
        raise ProtocolError("candidate archive does not match its SHA-256")
    return _unpack(
        archive,
        max_archive=MAX_CANDIDATE_ARCHIVE_BYTES,
        max_files=MAX_CANDIDATE_FILES,
        max_file=MAX_CANDIDATE_FILE_BYTES,
        max_total=MAX_CANDIDATE_TOTAL_BYTES,
    )
