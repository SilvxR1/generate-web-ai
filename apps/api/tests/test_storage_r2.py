"""CloudflareR2StorageProvider (app.storage.r2) — a fake, in-memory
boto3-shaped client throughout (no real R2/AWS network call anywhere in
this module). Verifies the save/load/delete/url_path contract, that
url_path returns an ABSOLUTE URL (unlike LocalStorageProvider's
root-relative path — see app.storage.provider.StorageProvider.url_path's
own docstring for why that's not a contract violation here), and the same
path-traversal/unsafe-key guard LocalStorageProvider applies."""

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.storage import absolute_url_path
from app.storage.errors import StorageProviderError
from app.storage.r2 import CloudflareR2StorageProvider


class _FakeS3Client:
    """In-memory stand-in for boto3's S3 client — only the handful of
    methods CloudflareR2StorageProvider actually calls."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.presigned_url_calls: list[dict] = []
        # None = normal behavior; set to an exception instance to make
        # the next/every put_object call raise it, simulating a real R2
        # failure (bad credentials, wrong bucket, network error) without
        # ever making a real network call.
        self.put_object_error: Exception | None = None

    def put_object(self, *, Bucket, Key, Body, ContentType=None):  # noqa: N803 — matches boto3's own casing
        if self.put_object_error is not None:
            raise self.put_object_error
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


# --- R2 failure mapping (hotfix: opaque 500 on /assets/{id}/replace) ------
#
# Before this hotfix, save() let a raw botocore exception (ClientError,
# BotoCoreError) propagate straight out of CloudflareR2StorageProvider —
# the exact same "opaque 500 instead of a structured error" class of bug
# PR #19 fixed for HiggsfieldCreativeProvider, but never applied to the R2
# storage layer PR #21 introduced. These two tests are the reproduction:
# a bad credential/bucket/account-id (ClientError) or a network failure
# (BotoCoreError/EndpointConnectionError) must surface as
# StorageProviderError, the one exception type app.routers.creative
# already knows how to map to a clean 502 — never the raw botocore type.


def test_save_wraps_a_client_error_as_storage_provider_error(
    provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client
):
    fake_client.put_object_error = ClientError(
        {"Error": {"Code": "SignatureDoesNotMatch", "Message": "bad credentials"}}, "PutObject"
    )

    with pytest.raises(StorageProviderError):
        provider.save(storage_key="biz-1/abc123.png", content=b"x")

    # Never partially recorded — a failed save leaves no trace to
    # mistake for a real, fetchable object.
    assert "biz-1/abc123.png" not in fake_client.objects


def test_save_wraps_a_network_error_as_storage_provider_error(
    provider: CloudflareR2StorageProvider, fake_client: _FakeS3Client
):
    fake_client.put_object_error = EndpointConnectionError(endpoint_url="https://acct-1.r2.cloudflarestorage.com")

    with pytest.raises(StorageProviderError):
        provider.save(storage_key="biz-1/abc123.png", content=b"x")
