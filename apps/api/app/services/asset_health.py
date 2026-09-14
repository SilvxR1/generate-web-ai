"""check_business_asset_availability — the ONE place a BusinessAsset row
is checked against its real, underlying storage object (P2 continuation:
persistent asset storage). A database row surviving a redeploy that
silently destroyed LocalStorageProvider's local disk (no R2 configured)
is exactly the production bug this exists to catch: `storage_url`/
`storage_key` remaining on the row is not proof the bytes still exist.

Never guesses: only a real StorageProvider.exists() call — a real, live
check — can mark an asset unavailable. An asset with no storage_key (a
legacy row from before this column existed, or one registered via
POST .../assets with an externally-hosted storage_url this codebase
never wrote) cannot be verified this way and is never falsely marked
either healthy or broken — see this function's own return contract.
"""

from app.db.models.business_asset import BusinessAsset
from app.storage.provider import StorageProvider

UNAVAILABLE_REASON = "Asset unavailable — please re-upload."


def check_business_asset_availability(asset: BusinessAsset, storage: StorageProvider) -> str | None:
    """Returns an operator/Studio-facing `unavailable_reason` string if
    the asset's own storage object is confirmed missing, None otherwise
    — None means "healthy" OR "not verifiable" (no storage_key), never
    conflated: a caller that wants to distinguish those two should check
    `asset.storage_key is None` itself, but must never treat "not
    verifiable" as "healthy" and skip re-checking once a key exists."""
    if not asset.storage_key:
        return None
    if storage.exists(asset.storage_key):
        return None
    return UNAVAILABLE_REASON
