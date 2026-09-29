"""Build once / promote (A8.3.4.1): the exact WebsiteArtifact a draft
built and validated is the artifact Publish deploys — never a rebuild.

Three separate concerns, deliberately kept apart:

1. Identity — `artifact_sha256`: a semantic SHA-256 over every file's
   root-relative path and bytes (security/runtime files such as
   `_headers`/`_redirects` included — the A8 CSP incident proved they are
   part of a site's behaviour), independent of dict/filesystem order and
   unambiguous (every field is length-prefixed). It never depends on the
   archive's own bytes, so gzip/tar metadata can never change identity.

2. Representation — `pack_artifact`/`unpack_artifact`: a tar.gz of
   regular files only, unpacked strictly in memory (never extracted to
   disk), rejecting traversal, absolute paths, duplicates, links, devices
   and oversized archives before a single byte reaches a WebsiteArtifact.

3. Persistence — `store_draft_artifact`/`load_draft_artifact`: through
   PrivateArtifactStorage only (A8.3.4.1b, app.storage.private — a
   separate, never-public R2 bucket in production; an unserved local
   directory in dev/test), write-once, under a tenant/business/draft-scoped
   key. The public asset provider can't be passed here (wrong type), and
   the private wrapper has no URL capability at all: the key is an
   internal identifier, never a URL. Loading always recomputes the
   semantic hash and refuses on any mismatch — there is no "repair" or
   silent rebuild path.
"""

import gzip
import hashlib
import io
import logging
import tarfile
from dataclasses import dataclass
from uuid import UUID

from app.publishing.publisher import WebsiteArtifact
from app.storage.errors import StorageProviderError
from app.storage.private import PrivateArtifactStorage

logger = logging.getLogger(__name__)

# Bumping this changes every artifact's identity — only ever done together
# with a migration path for already-stored draft hashes.
_HASH_DOMAIN = b"generate-web-ai/website-artifact/v1\x00"
_ARCHIVE_CONTENT_TYPE = "application/gzip"

# Generous bounds for a static marketing site, tight enough that a corrupt
# or hostile archive can never exhaust memory while being unpacked.
MAX_ARTIFACT_FILES = 5_000
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024
_MAX_PATH_LENGTH = 1_024


class ArtifactError(Exception):
    """Base for every stored-artifact failure. `str(exc)` is an internal
    diagnostic (safe to log: ids, short hashes, never file contents);
    callers map `code` onto their own owner-facing message."""

    code = "artifact_error"


class ArtifactPathError(ArtifactError):
    code = "artifact_path_invalid"


class ArtifactArchiveCorruptError(ArtifactError):
    code = "artifact_archive_corrupt"


class ArtifactUnavailableError(ArtifactError):
    code = "artifact_unavailable"


class ArtifactIntegrityError(ArtifactError):
    code = "artifact_integrity_mismatch"


class ArtifactAlreadyExistsError(ArtifactError):
    code = "artifact_already_exists"


@dataclass(frozen=True)
class StoredArtifact:
    storage_key: str
    sha256: str


def short_hash(value: str | None) -> str | None:
    return value[:12] if value else None


def validate_artifact_path(path: str) -> None:
    """A WebsiteArtifact key must be a plain, root-relative POSIX path —
    the shape app.publishing.build/_read_artifact produces. Anything that
    could resolve outside the site root (or mean different things to
    different consumers) is rejected rather than normalized."""
    if not path or len(path) > _MAX_PATH_LENGTH:
        raise ArtifactPathError(f"artifact path has invalid length ({len(path)})")
    if "\x00" in path or "\\" in path:
        raise ArtifactPathError(f"artifact path contains a forbidden character: {path!r}")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise ArtifactPathError(f"artifact path is absolute: {path!r}")
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        raise ArtifactPathError(f"artifact path is not normalized: {path!r}")


def artifact_sha256(artifact: WebsiteArtifact) -> str:
    """Canonical identity of a deployable website: every file path and
    its exact bytes, sorted by path, each field length-prefixed so no two
    different file sets can serialize to the same byte stream."""
    digest = hashlib.sha256(_HASH_DOMAIN)
    entry = artifact.entry_point.encode("utf-8")
    digest.update(len(entry).to_bytes(8, "big"))
    digest.update(entry)
    digest.update(len(artifact.files).to_bytes(8, "big"))
    for path in sorted(artifact.files):
        validate_artifact_path(path)
        encoded_path = path.encode("utf-8")
        content = artifact.files[path]
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def pack_artifact(artifact: WebsiteArtifact) -> bytes:
    """Deterministic tar.gz (sorted entries, zeroed mtimes/owners, gzip
    mtime 0) — reproducible as a convenience, but identity is always the
    semantic hash above, never these bytes."""
    if artifact.entry_point != "index.html":
        # The archive stores files only; every build path in this codebase
        # uses the default entry point, so refuse anything else rather than
        # silently losing it on the way back in.
        raise ArtifactPathError(f"unsupported entry point: {artifact.entry_point!r}")
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(artifact.files):
            validate_artifact_path(path)
            content = artifact.files[path]
            info = tarfile.TarInfo(name=path)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(content))
    gz_buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=gz_buffer, mtime=0) as gz:
        gz.write(tar_buffer.getvalue())
    return gz_buffer.getvalue()


def unpack_artifact(archive: bytes) -> WebsiteArtifact:
    """Reads a pack_artifact archive back into memory. Never touches the
    filesystem, so a hostile member name can't escape anywhere — and is
    still rejected outright rather than trusted."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar:
                if not member.isreg():
                    raise ArtifactArchiveCorruptError(
                        f"archive member {member.name!r} is not a regular file (type {member.type!r})"
                    )
                try:
                    validate_artifact_path(member.name)
                except ArtifactPathError as exc:
                    raise ArtifactArchiveCorruptError(str(exc)) from exc
                if member.name in files:
                    raise ArtifactArchiveCorruptError(f"archive contains duplicate path {member.name!r}")
                if len(files) >= MAX_ARTIFACT_FILES:
                    raise ArtifactArchiveCorruptError(f"archive exceeds {MAX_ARTIFACT_FILES} files")
                total += member.size
                if total > MAX_ARTIFACT_BYTES:
                    raise ArtifactArchiveCorruptError(f"archive exceeds {MAX_ARTIFACT_BYTES} bytes")
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ArtifactArchiveCorruptError(f"archive member {member.name!r} has no content")
                content = extracted.read()
                if len(content) != member.size:
                    raise ArtifactArchiveCorruptError(f"archive member {member.name!r} is truncated")
                files[member.name] = content
    except ArtifactArchiveCorruptError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as exc:
        raise ArtifactArchiveCorruptError(f"archive could not be read: {type(exc).__name__}") from exc

    if "index.html" not in files:
        raise ArtifactArchiveCorruptError("archive has no index.html")
    return WebsiteArtifact(files=files)


def draft_artifact_storage_key(*, tenant_id: UUID, business_id: UUID, draft_id: UUID) -> str:
    return f"website-drafts/{tenant_id.hex}/{business_id.hex}/{draft_id.hex}/artifact.tar.gz"


def version_artifact_storage_key(*, tenant_id: UUID, business_id: UUID, version_id: UUID) -> str:
    """v0.2 S1: where a version-scoped artifact lives — only for a publish
    that built its own artifact (the legacy SiteConfig path), so that every
    new WebsiteVersion is artifact-backed. Promoted drafts keep their draft
    key; nothing is copied."""
    return f"website-versions/{tenant_id.hex}/{business_id.hex}/{version_id.hex}/artifact.tar.gz"


def _store_artifact(
    storage: PrivateArtifactStorage,
    *,
    storage_key: str,
    artifact: WebsiteArtifact,
    kind: str,
    ref: UUID,
    business_id: UUID,
) -> StoredArtifact:
    sha256 = artifact_sha256(artifact)
    archive = pack_artifact(artifact)
    # Prove the stored representation reproduces the validated bytes
    # *before* anything is persisted — a packing bug must fail draft
    # creation, not surface later as a publish-time integrity mismatch.
    if artifact_sha256(unpack_artifact(archive)) != sha256:
        raise ArtifactIntegrityError("packed archive does not reproduce the validated artifact")

    # Write-once: a stored artifact is immutable. StorageProvider has no
    # conditional put, so this is an application-level guard; the key
    # embeds a fresh, unique id, so it can only trip on a bug.
    if storage.exists(storage_key):
        raise ArtifactAlreadyExistsError(f"an artifact already exists for {kind} {ref}")
    storage.save(storage_key=storage_key, content=archive, content_type=_ARCHIVE_CONTENT_TYPE)
    logger.info(
        "website_artifact_stored %s=%s business=%s sha256=%s files=%d archive_bytes=%d",
        kind,
        ref,
        business_id,
        short_hash(sha256),
        len(artifact.files),
        len(archive),
    )
    return StoredArtifact(storage_key=storage_key, sha256=sha256)


def store_draft_artifact(
    storage: PrivateArtifactStorage,
    *,
    tenant_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    artifact: WebsiteArtifact,
) -> StoredArtifact:
    """Hashes, packs, round-trip-verifies and saves `artifact` exactly
    once. Raises ArtifactError/StorageProviderError on any failure — the
    caller must then never mark the draft publishable."""
    return _store_artifact(
        storage,
        storage_key=draft_artifact_storage_key(tenant_id=tenant_id, business_id=business_id, draft_id=draft_id),
        artifact=artifact,
        kind="draft",
        ref=draft_id,
        business_id=business_id,
    )


def store_version_artifact(
    storage: PrivateArtifactStorage,
    *,
    tenant_id: UUID,
    business_id: UUID,
    version_id: UUID,
    artifact: WebsiteArtifact,
) -> StoredArtifact:
    """v0.2 S1: same write-once, round-trip-verified storage as a draft
    artifact, keyed by the WebsiteVersion about to be recorded."""
    return _store_artifact(
        storage,
        storage_key=version_artifact_storage_key(tenant_id=tenant_id, business_id=business_id, version_id=version_id),
        artifact=artifact,
        kind="version",
        ref=version_id,
        business_id=business_id,
    )


def load_artifact(
    storage: PrivateArtifactStorage, *, storage_key: str, expected_sha256: str, kind: str, ref: UUID
) -> WebsiteArtifact:
    """Loads, unpacks and integrity-verifies a stored artifact. Never
    rebuilds and never repairs: any failure raises (ArtifactUnavailableError,
    ArtifactArchiveCorruptError, ArtifactIntegrityError). Logs only ids and
    short hashes — never keys' contents, archive bytes or credentials."""
    try:
        archive = storage.load(storage_key)
    except (StorageProviderError, OSError, ValueError) as exc:
        logger.error(
            "website_artifact_missing %s=%s sha256=%s error=%s",
            kind,
            ref,
            short_hash(expected_sha256),
            type(exc).__name__,
        )
        raise ArtifactUnavailableError(f"stored artifact for {kind} {ref} could not be loaded") from exc

    try:
        artifact = unpack_artifact(archive)
        actual_sha256 = artifact_sha256(artifact)
    except ArtifactError as exc:
        logger.error(
            "website_artifact_integrity_mismatch %s=%s expected=%s reason=corrupt detail=%s",
            kind,
            ref,
            short_hash(expected_sha256),
            exc,
        )
        raise ArtifactArchiveCorruptError(f"stored artifact for {kind} {ref} is corrupt: {exc}") from exc

    logger.info("website_artifact_loaded %s=%s files=%d", kind, ref, len(artifact.files))
    if actual_sha256 != expected_sha256:
        logger.error(
            "website_artifact_integrity_mismatch %s=%s expected=%s actual=%s",
            kind,
            ref,
            short_hash(expected_sha256),
            short_hash(actual_sha256),
        )
        raise ArtifactIntegrityError(
            f"stored artifact for {kind} {ref} failed integrity verification "
            f"(expected {short_hash(expected_sha256)}, got {short_hash(actual_sha256)})"
        )
    logger.info("website_artifact_integrity_verified %s=%s sha256=%s", kind, ref, short_hash(actual_sha256))
    return artifact


def load_draft_artifact(
    storage: PrivateArtifactStorage, *, storage_key: str, expected_sha256: str, draft_id: UUID
) -> WebsiteArtifact:
    """Loads, unpacks and integrity-verifies a stored draft artifact.
    Never rebuilds and never repairs: any failure raises."""
    return load_artifact(storage, storage_key=storage_key, expected_sha256=expected_sha256, kind="draft", ref=draft_id)
