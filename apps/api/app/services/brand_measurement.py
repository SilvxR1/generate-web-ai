"""Brand measurement service (P2.6) — the ONE place an official logo's bytes
are read for Brand Intelligence.

It reads through the existing `StorageProvider.load` abstraction only: no new
R2 access path, no presigned or public URL, no download of an arbitrary
`storage_url` (so no SSRF surface), no temp files — bytes live in memory just
long enough to be measured and are never logged, stored or returned.

TENANT ISOLATION. The assets handed in come from the tenant-scoped repository
(app.repositories.business_asset). As defence in depth this service also
refuses any asset whose recorded storage provider is not the current one, or
whose storage key is not under `<business_id>/` (the key layout
app.storage.keys.generate_storage_key always produces), so one business's
brand measurement can never read another business's object.

NON-CRITICAL BY CONTRACT. Every failure — a missing object, a storage error, a
malformed or oversized image — becomes a `failed` measurement value with a
stable code; nothing here can raise into the generation path. A brief without
measurements simply plans exactly as P2.5 did.
"""

import logging
from uuid import UUID

from app.domain.creative.brand_intelligence import (
    FAIL_UNREADABLE,
    BrandAssetMeasurement,
    failed_measurement,
    measure_asset_palette,
)
from app.domain.creative.brand_profile import official_logos
from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.enums import BrandStrategy
from app.storage.provider import StorageProvider

logger = logging.getLogger(__name__)


def _key_belongs_to_business(storage_key: str, business_id: UUID) -> bool:
    parts = storage_key.split("/")
    return (
        storage_key.startswith(f"{business_id}/")
        and ".." not in parts
        and "" not in parts[1:]
        and "\\" not in storage_key
    )


def _measure_logo(logo: CreativeBriefAsset, *, storage: StorageProvider, business_id: UUID) -> BrandAssetMeasurement:
    key = logo.storage_key
    # Only an object this backend itself wrote to the CURRENT provider is read;
    # an externally-hosted URL or a legacy row is never fetched or guessed at.
    if not key or logo.storage_provider != storage.provider_name or not _key_belongs_to_business(key, business_id):
        return failed_measurement(logo.id, FAIL_UNREADABLE)
    try:
        data = storage.load(key)
    except Exception:  # noqa: BLE001 — missing object, R2 error, ...: non-critical
        return failed_measurement(logo.id, FAIL_UNREADABLE)
    return measure_asset_palette(logo.id, data)


def measure_brand_assets(
    brief: CreativeBrief, *, storage: StorageProvider, business_id: UUID
) -> list[BrandAssetMeasurement]:
    """Measure the official logo(s) — but only when the measurement can matter:
    explicit brand colors outrank measured ones, and a NEW_DIRECTION is not
    constrained by the existing identity, so neither reads any bytes."""
    if brief.brand_colors is not None or brief.brand_strategy is BrandStrategy.NEW_DIRECTION:
        return []
    measurements: list[BrandAssetMeasurement] = []
    for logo in official_logos(brief.available_assets):
        measurement = _measure_logo(logo, storage=storage, business_id=business_id)
        if measurement.failure_code:
            # Code only: never bytes, URLs, keys or exception text.
            logger.warning("brand_measurement_failed asset_id=%s code=%s", logo.id, measurement.failure_code)
        measurements.append(measurement)
    return measurements


def with_brand_measurements(brief: CreativeBrief, *, storage: StorageProvider, business_id: UUID) -> CreativeBrief:
    """`brief` plus its brand measurements. Never raises: if measuring itself
    fails unexpectedly the brief is returned unchanged (P2.5 behavior)."""
    try:
        measurements = measure_brand_assets(brief, storage=storage, business_id=business_id)
    except Exception:  # noqa: BLE001 — Brand Intelligence must never block generation
        logger.warning("brand_measurement_unexpected_failure")
        return brief
    return brief.model_copy(update={"brand_measurements": measurements})
