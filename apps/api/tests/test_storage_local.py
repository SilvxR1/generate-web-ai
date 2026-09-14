"""LocalStorageProvider (app.storage.local) and generate_storage_key
(app.storage.keys): safe filenames, path-traversal rejection (Phase 3),
and the round-trip save/url_path/delete contract."""

import pytest

from app.storage import LocalStorageProvider, generate_storage_key


@pytest.fixture()
def provider(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(root_dir=tmp_path)


def test_generate_storage_key_never_reuses_the_original_filename():
    key = generate_storage_key(business_id="biz-1", original_filename="../../etc/passwd")

    assert "passwd" not in key
    assert ".." not in key
    assert key.startswith("biz-1/")


def test_generate_storage_key_preserves_a_safe_extension():
    key = generate_storage_key(business_id="biz-1", original_filename="logo.PNG")

    assert key.endswith(".png")


def test_save_and_url_path_round_trip(provider: LocalStorageProvider, tmp_path):
    key = "biz-1/abc123.png"

    stored = provider.save(storage_key=key, content=b"hello")

    assert stored.storage_key == key
    assert provider.url_path(key) == "/uploads/biz-1/abc123.png"
    assert (tmp_path / key).read_bytes() == b"hello"


def test_delete_is_idempotent(provider: LocalStorageProvider):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"hello")

    provider.delete(key)
    provider.delete(key)  # must not raise the second time


def test_rejects_a_path_traversal_key(provider: LocalStorageProvider):
    with pytest.raises(ValueError):
        provider.save(storage_key="../../etc/passwd", content=b"pwned")


def test_rejects_a_key_outside_the_storage_root(provider: LocalStorageProvider):
    with pytest.raises(ValueError):
        provider.save(storage_key="biz-1/../../outside.png", content=b"pwned")


def test_exists_is_true_after_save_and_false_after_delete(provider: LocalStorageProvider):
    key = "biz-1/abc123.png"
    assert provider.exists(key) is False

    provider.save(storage_key=key, content=b"hello")
    assert provider.exists(key) is True

    provider.delete(key)
    assert provider.exists(key) is False


def test_presigned_url_returns_none_no_signing_concept_in_local_dev(provider: LocalStorageProvider):
    key = "biz-1/abc123.png"
    provider.save(storage_key=key, content=b"hello")

    assert provider.presigned_url(key, expires_in_seconds=60) is None


def test_a_saved_object_survives_a_fresh_provider_instance_pointed_at_the_same_root(tmp_path):
    """P2 continuation (persistent asset storage): proves the object lives
    in the directory itself, not in any in-process state — the same
    guarantee an R2 bucket gives for free, and the reason a real BusinessAsset
    upload's storage_key must be enough on its own to find the bytes again
    after an API restart (a new LocalStorageProvider instance, same root)."""
    key = "biz-1/abc123.png"
    LocalStorageProvider(root_dir=tmp_path).save(storage_key=key, content=b"hello")

    reinstantiated = LocalStorageProvider(root_dir=tmp_path)
    assert reinstantiated.exists(key) is True
    assert reinstantiated.load(key) == b"hello"
