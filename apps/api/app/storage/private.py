"""PrivateArtifactStorage (A8.3.4.1b) — backend-only object storage for
unpublished internal artifacts (WebsiteDraft deployable archives, see
app.publishing.artifact_store).

A capability wrapper, not a new storage implementation: it holds an
ordinary StorageProvider (a CloudflareR2StorageProvider pointed at a
separate, never-public bucket in production; a LocalStorageProvider on a
directory that is never mounted over HTTP in dev/test) and exposes ONLY
save/load/exists/delete. There is no url_path/presigned_url here, so no
caller can accidentally turn a private artifact into a URL, and
artifact_store's functions are typed to require this class, so the public
asset provider can't be passed in by mistake either.

Constructed only by app.dependencies.get_private_artifact_storage, which
fails closed — it never falls back to the public bucket.
"""

from pathlib import Path

from app.storage.local import LocalStorageProvider
from app.storage.provider import StorageProvider, StoredFile
from app.storage.r2 import CloudflareR2StorageProvider


class PrivateArtifactStorage:
    def __init__(self, backend: StorageProvider, *, public_upload_dir: Path | None = None) -> None:
        if isinstance(backend, CloudflareR2StorageProvider) and backend.is_public:
            raise ValueError("private artifact storage cannot use an R2 bucket that has a public base URL")
        if isinstance(backend, LocalStorageProvider) and public_upload_dir is not None:
            root = backend.root_dir.resolve()
            public = public_upload_dir.resolve()
            if root == public or public in root.parents:
                raise ValueError("private artifact storage cannot live inside the public /uploads directory")
        self._backend = backend

    @property
    def provider_name(self) -> str:
        return self._backend.provider_name

    def save(self, *, storage_key: str, content: bytes, content_type: str | None = None) -> StoredFile:
        return self._backend.save(storage_key=storage_key, content=content, content_type=content_type)

    def load(self, storage_key: str) -> bytes:
        return self._backend.load(storage_key)

    def exists(self, storage_key: str) -> bool:
        return self._backend.exists(storage_key)

    def delete(self, storage_key: str) -> None:
        self._backend.delete(storage_key)
