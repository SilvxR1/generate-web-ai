"""StorageProvider — where a business asset's bytes actually live once
uploaded through this backend (Phase 3: usable asset ingestion, not just
a caller-supplied URL reference). LocalStorageProvider (app.storage.local)
is the first, dev-only implementation; a future S3/Cloudflare R2 provider
implements this same interface without any router/service code changing —
mirrors WebsitePublisher/CreativeProvider's own ABC-plus-swappable-
implementation shape already used elsewhere in this codebase.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class StoredFile:
    """What a successful save produces — provider-neutral, never a raw
    filesystem path a caller could use to escape the storage root."""

    storage_key: str


class StorageProvider(ABC):
    # A stable, persisted identity for "which provider actually wrote
    # this object" (app.db.models.business_asset.BusinessAsset.storage_provider)
    # — recorded once at upload time so a later caller (a broken-asset
    # check, a presigned-URL request) never has to guess which provider's
    # `exists`/`presigned_url` to call for an existing row, even if the
    # server's *current* get_storage_provider() selection later changes.
    provider_name: ClassVar[str]

    @abstractmethod
    def save(self, *, storage_key: str, content: bytes, content_type: str | None = None) -> StoredFile:
        """`content_type` (e.g. 'image/jpeg') is stored alongside the
        object when the provider supports it (R2/S3's own ContentType
        metadata) so a later fetch — by a browser, or Higgsfield — gets
        the real MIME type instead of a generic
        'application/octet-stream'. LocalStorageProvider ignores it: its
        StaticFiles mount already infers content-type from the file
        extension at serve time."""

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        """Idempotent: deleting an already-gone key must not raise."""

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        """Real, on-demand existence check — never inferred from a
        database row alone (P2.1 continuation: a BusinessAsset row
        surviving a redeploy that silently destroyed
        LocalStorageProvider's underlying files is exactly the bug this
        method exists to catch, see app.services.asset_health)."""

    @abstractmethod
    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        """A short-lived, provider-fetchable URL for a private object —
        for a Creative Director provider (Higgsfield) to fetch a
        business's own reference asset without that asset needing to be
        permanently, unlistedly public. Returns None when this provider
        has no signing concept at all (LocalStorageProvider — there is
        no "private" object to begin with in local dev/test); a caller
        receiving None must fall back to `url_path` unchanged, never
        treat it as an error."""

    @abstractmethod
    def url_path(self, storage_key: str) -> str:
        """Where this file is servable once saved — either a root-relative
        URL path (e.g. '/uploads/<key>', LocalStorageProvider: the caller,
        a router that knows the incoming request's real host, turns this
        into an absolute URL) or a full absolute URL
        (app.storage.r2.CloudflareR2StorageProvider: R2 serves objects
        from its own public bucket domain, a real *configured* value, not
        guessed — see that class's own docstring). Every caller that
        prepends its own host to this value (app.routers.creative, the
        Studio frontend) must check for an already-absolute URL first —
        see absolute_url_path below."""

    @abstractmethod
    def load(self, storage_key: str) -> bytes:
        """Reads a previously-saved file back server-side (P2: needed to
        republish a GenerativeWebsiteArtifact's archived source without
        re-invoking the AI Frontend Engineer — see
        app.publishing.service.publish_generative_website). Every real
        business asset was already reachable via `url_path` over HTTP;
        this is the one case this codebase needs the bytes back
        in-process instead."""


def absolute_url_path(url_path: str, *, request_base_url: str) -> str:
    """Turns any StorageProvider.url_path() result into an absolute URL a
    browser/external service (e.g. Higgsfield) can actually fetch —
    root-relative paths get `request_base_url` prepended;
    already-absolute URLs (app.storage.r2.CloudflareR2StorageProvider)
    pass through unchanged. Every call site that used to blindly
    concatenate `request_base_url + storage.url_path(...)` must go
    through this instead now that a provider may return either shape."""
    if url_path.startswith("http://") or url_path.startswith("https://"):
        return url_path
    return f"{request_base_url.rstrip('/')}{url_path}"
