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
