"""Website version history + rollback (P0 Phase 20-22; v0.2 S1).

Invariant (v0.2 S1): publishing and rollback operate on immutable
WebsiteArtifacts, not on reconstructed website configuration.

Rollback modes, chosen ONLY from the target version's own provenance:

- ARTIFACT (every version with `artifact_sha256`): load the exact stored
  artifact (the version's own `artifact_key`, or — for rows recorded before
  S1 — its source draft's key, accepted only when that draft's recorded
  hash equals the version's), verify its SHA-256, and redeploy the SAME
  bytes through publish_prebuilt_artifact. Zero builds, zero generators,
  zero providers. Any failure (missing, unloadable, corrupt, wrong hash,
  inconsistent provenance) fails closed — never a rebuild.
- LEGACY REBUILD (only rows without `artifact_sha256`, i.e. published before
  artifacts were recorded, whose `site_config` is a real SiteConfig):
  rebuilds that SiteConfig with today's renderer. This is legacy
  compatibility and does NOT provide the exact-byte guarantee. The
  resulting new version stores the artifact it built, so it is itself
  artifact-backed from then on.
- Anything else (e.g. a generative snapshot without an artifact) is
  refused with a clean 409, never a 500.

Every rollback is recorded as a NEW WebsiteVersion
(`rolled_back_from_version_id` = the restored version). Historical rows
are never modified or deleted, and a failed rollback leaves the live site
untouched and records nothing.

PlatformContract is deliberately NOT re-run on rollback: the artifact
already passed it when first validated, and a contract that has evolved
since must not block restoring a previously live site. Integrity
verification is mandatory regardless.
"""

import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models.website_version import WebsiteVersion
from app.publishing.artifact_store import (
    ArtifactError,
    ArtifactUnavailableError,
    load_artifact,
    short_hash,
)
from app.publishing.publisher import WebsiteArtifact, WebsitePublisher
from app.publishing.service import (
    WebsitePublishError,
    WebsiteStateResult,
    publish_prebuilt_artifact,
    publish_website,
)
from app.repositories.website_draft import WebsiteDraftRepository
from app.repositories.website_version import WebsiteVersionRepository
from app.schemas.site_config import SiteConfigPayload
from app.schemas.website_version import WebsiteVersionSummary
from app.storage.private import PrivateArtifactStorage

logger = logging.getLogger(__name__)

_ARTIFACT_UNAVAILABLE_MESSAGE = (
    "This version's stored website could not be loaded right now. Nothing was changed; please try again."
)
_ARTIFACT_UNVERIFIED_MESSAGE = (
    "This version's stored website failed its integrity check, so it cannot be restored. Nothing was changed."
)
_NOT_RESTORABLE_MESSAGE = "This version cannot be restored. Nothing was changed."


def list_website_versions(*, session: Session, tenant_id: UUID, business_id: UUID) -> list[WebsiteVersionSummary]:
    """Most recent first; the first entry (if any) is flagged
    `is_current` — never independently recomputed from the live Website
    row, since a version is created inside the very same publish
    transaction that updates it, so the two can never disagree."""
    versions = WebsiteVersionRepository(session).list_for_business(tenant_id, business_id)
    return [
        WebsiteVersionSummary(
            id=version.id, published_at=version.published_at, deploy_url=version.deploy_url, is_current=index == 0
        )
        for index, version in enumerate(versions)
    ]


def _artifact_key_for(session: Session, version: WebsiteVersion) -> str:
    """The durable key of the version's exact artifact. Pre-S1 rows have
    no `artifact_key`; their source draft's key is used only when that
    draft (same tenant/business) recorded the SAME hash — otherwise the
    provenance is inconsistent and the rollback is refused."""
    if version.artifact_key:
        return version.artifact_key
    if version.source_website_draft_id is not None:
        draft = WebsiteDraftRepository(session).get_for_business(
            version.tenant_id, version.business_id, version.source_website_draft_id
        )
        if draft is not None and draft.artifact_key and draft.artifact_sha256 == version.artifact_sha256:
            return draft.artifact_key
    logger.error(
        "website_rollback_refused version=%s business=%s reason=artifact_provenance_unavailable sha256=%s",
        version.id,
        version.business_id,
        short_hash(version.artifact_sha256),
    )
    raise WebsitePublishError(_NOT_RESTORABLE_MESSAGE, code="website_version_not_restorable", status_code=409)


def _load_version_artifact(
    session: Session, version: WebsiteVersion, artifact_storage: PrivateArtifactStorage
) -> tuple[str, WebsiteArtifact]:
    assert version.artifact_sha256 is not None
    key = _artifact_key_for(session, version)
    try:
        artifact = load_artifact(
            artifact_storage, storage_key=key, expected_sha256=version.artifact_sha256, kind="version", ref=version.id
        )
    except ArtifactUnavailableError as exc:
        raise WebsitePublishError(
            _ARTIFACT_UNAVAILABLE_MESSAGE, code="website_version_artifact_unavailable", status_code=503
        ) from exc
    except ArtifactError as exc:
        raise WebsitePublishError(
            _ARTIFACT_UNVERIFIED_MESSAGE, code="website_version_artifact_integrity_failed", status_code=409
        ) from exc
    return key, artifact


def rollback_to_version(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    version_id: UUID,
    publisher: WebsitePublisher,
    artifact_storage: PrivateArtifactStorage,
) -> WebsiteStateResult:
    version = WebsiteVersionRepository(session).get_for_business(tenant_id, business_id, version_id)
    if version is None:
        raise WebsitePublishError(
            "This website version was not found.", code="website_version_not_found", status_code=404
        )

    if version.artifact_sha256 is not None:
        # ARTIFACT mode — exact bytes, never a rebuild, no fallback.
        key, artifact = _load_version_artifact(session, version, artifact_storage)
        result = publish_prebuilt_artifact(
            session=session,
            tenant_id=tenant_id,
            business_id=business_id,
            artifact=artifact,
            config=dict(version.site_config or {}),
            publisher=publisher,
            source_website_draft_id=version.source_website_draft_id,
            artifact_sha256=version.artifact_sha256,
            artifact_key=key,
            rolled_back_from_version_id=version.id,
        )
        logger.info(
            "website_rollback mode=artifact business=%s target_version=%s sha256=%s outcome=deployed",
            business_id,
            version.id,
            short_hash(version.artifact_sha256),
        )
        return result

    # LEGACY REBUILD mode — only for historical rows without an artifact.
    # Not exact-byte. A generative snapshot has no SiteConfig to rebuild.
    config = version.site_config or {}
    if config.get("engine") == "generative":
        raise WebsitePublishError(_NOT_RESTORABLE_MESSAGE, code="website_version_not_restorable", status_code=409)
    try:
        site_config = SiteConfigPayload.model_validate(config)
    except ValidationError as exc:
        raise WebsitePublishError(
            _NOT_RESTORABLE_MESSAGE, code="website_version_not_restorable", status_code=409
        ) from exc
    logger.warning(
        "website_rollback mode=legacy_rebuild business=%s target_version=%s (not exact-byte)",
        business_id,
        version.id,
    )
    return publish_website(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        site_config=site_config,
        publisher=publisher,
        artifact_storage=artifact_storage,
        rolled_back_from_version_id=version.id,
    )
