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


@dataclass(frozen=True)
class StoredFile:
    """What a successful save produces — provider-neutral, never a raw
    filesystem path a caller could use to escape the storage root."""

    storage_key: str


class StorageProvider(ABC):
    @abstractmethod
    def save(self, *, storage_key: str, content: bytes) -> StoredFile: ...

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        """Idempotent: deleting an already-gone key must not raise."""

    @abstractmethod
    def url_path(self, storage_key: str) -> str:
        """A root-relative URL path (e.g. '/uploads/<key>') this file is
        servable at once saved. The caller (a router, which knows the
        incoming request's real host) turns this into an absolute URL —
        this layer never guesses its own public hostname."""

    @abstractmethod
    def load(self, storage_key: str) -> bytes:
        """Reads a previously-saved file back server-side (P2: needed to
        republish a GenerativeWebsiteArtifact's archived source without
        re-invoking the AI Frontend Engineer — see
        app.publishing.service.publish_generative_website). Every real
        business asset was already reachable via `url_path` over HTTP;
        this is the one case this codebase needs the bytes back
        in-process instead."""
