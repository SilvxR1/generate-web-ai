"""CloudflareR2StorageProvider (app.storage.r2) — a fake, in-memory
boto3-shaped client throughout (no real R2/AWS network call anywhere in
this module). Verifies the save/load/delete/url_path contract, that
url_path returns an ABSOLUTE URL (unlike LocalStorageProvider's
root-relative path — see app.storage.provider.StorageProvider.url_path's
own docstring for why that's not a contract violation here), and the same
path-traversal/unsafe-key guard LocalStorageProvider applies."""

import pytest
from botocore.exceptions import ClientError

from app.storage import absolute_url_path
from app.storage.r2 import CloudflareR2StorageProvider


class _FakeS3Client:
    """In-memory stand-in for boto3's S3 client — only the handful of
    methods CloudflareR2StorageProvider actually calls."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.presigned_url_calls: list[dict] = []

    def put_object(self, *, Bucket, Key, Body, ContentType=None):  # noqa: N803 — matches boto3's own casing
        self.objects[Key] = Body
        if ContentType:
            self.content_types[Key] = ContentType

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        return {"Body": _FakeBody(self.objects[Key])}

    def head_object(self, *, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "not found"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):  # noqa: N803
        self.presigned_url_calls.append({"operation": operation, "params": Params, "expires_in": ExpiresIn})
        return f"https://pub-abc123.r2.dev/{Params['Key']}?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=fake"


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


@pytest.fixture()
def fake_client() -> _FakeS3Client:
    return _FakeS3Client()


@pytest.fixture()
def provider(fake_client: _FakeS3Client) -> CloudflareR2StorageProvider:
    return CloudflareR2StorageProvider(
        account_id="acct-1",
        access_key_id="ak",
        secret_access_key="sk",
        bucket_name="gwa-artifacts",
        public_base_url="https://pub-abc123.r2.dev",
        client=fake_client,
    )


def test_save_load_round_trip(provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client):
    key = "biz-1/abc123.gz"
    stored = provider.save(storage_key=key, content=b"archive-bytes")

    assert stored.storage_key == key
    assert provider.load(key) == b"archive-bytes"
    assert fake_client.objects[key] == b"archive-bytes"


def test_url_path_returns_an_absolute_url(provider: CloudflareR2StorageProvider):
    url = provider.url_path("biz-1/abc123.png")
    assert url == "https://pub-abc123.r2.dev/biz-1/abc123.png"
    # absolute_url_path must pass this through unchanged, never
    # double-prepending a request host onto an already-absolute R2 URL.
    assert absolute_url_path(url, request_base_url="https://api.example.com") == url


def test_delete_is_idempotent(provider: CloudflareR2StorageProvider):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"x")

    provider.delete(key)
    provider.delete(key)  # must not raise the second time (key already gone)


def test_delete_of_a_never_existing_key_does_not_raise(provider: CloudflareR2StorageProvider):
    provider.delete("biz-1/never-existed.png")


def test_rejects_a_path_traversal_key(provider: CloudflareR2StorageProvider):
    with pytest.raises(ValueError):
        provider.save(storage_key="../../etc/passwd", content=b"pwned")


def test_rejects_a_key_outside_the_storage_root_shape(provider: CloudflareR2StorageProvider):
    with pytest.raises(ValueError):
        provider.save(storage_key="biz-1/../../outside.png", content=b"pwned")


def test_save_records_a_real_content_type(provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"x", content_type="image/png")

    assert fake_client.content_types[key] == "image/png"


def test_save_without_a_content_type_sends_none(provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"x")

    assert key not in fake_client.content_types


def test_exists_is_true_for_a_present_key(provider: CloudflareR2StorageProvider):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"x")

    assert provider.exists(key) is True


def test_exists_is_false_for_a_missing_key(provider: CloudflareR2StorageProvider):
    """The exact production bug this hotfix exists to catch: a
    BusinessAsset DB row can point at a storage_key whose real R2 object
    was never actually written (or has since been removed) — exists()
    must report that honestly rather than assuming presence."""
    assert provider.exists("biz-1/never-uploaded.png") is False


def test_presigned_url_returns_a_real_url_and_forwards_the_expiry(
    provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client
):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"x")

    url = provider.presigned_url(key, expires_in_seconds=600)

    assert url is not None
    assert key in url
    assert fake_client.presigned_url_calls == [
        {"operation": "get_object", "params": {"Bucket": "gwa-artifacts", "Key": key}, "expires_in": 600}
    ]


def test_presigned_url_rejects_a_path_traversal_key(provider: CloudflareR2StorageProvider):
    with pytest.raises(ValueError):
        provider.presigned_url("../../etc/passwd", expires_in_seconds=600)
