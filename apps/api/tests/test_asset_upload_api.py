"""POST /businesses/{id}/assets/upload (app.routers.creative): real file
ingestion — content-type validation, size limits, safe storage keys,
tenant/business scoping, and that deletion is scoped to its own business.
Phase 19: 'asset upload; tenant isolation; cross-tenant asset access;
asset deletion ownership; invalid asset type; invalid/oversized upload.'
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.tenant import Tenant
from app.dependencies import get_rate_limiter, get_session, get_storage_provider
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter
from app.storage.errors import StorageProviderError
from app.storage.provider import StorageProvider, StoredFile


@pytest.fixture()
def client(session, tmp_path, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    # Every test gets its own throwaway upload directory — never the
    # real apps/api/var/uploads a developer might be running against.
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)
    # Isolates this test from whatever internal_api_base_url a developer's
    # own environment happens to have configured (e.g. a docker-compose
    # setup pointing it at host.docker.internal) — app.routers.creative's
    # _public_base_url (Phase 8 hotfix) prefers a real configured value
    # over the test client's own host, exactly as it should in production,
    # so this test asserts against a known value instead of the ambient one.
    monkeypatch.setattr(settings, "internal_api_base_url", "http://testserver")

    app.dependency_overrides[get_session] = _override_get_session
    # A fresh limiter per test — otherwise every test in this module (many
    # of which now call the shared asset_upload rate-limit bucket via
    # upload/upload-batch/replace) would drain one process-wide
    # InMemoryRateLimiter, causing later tests to fail with an unrelated
    # 429 (same convention tests/test_generative_pipeline_capability.py
    # already uses for its own rate-limited endpoint).
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _headers(tenant_id: uuid.UUID) -> dict:
    return {"X-Tenant-Id": str(tenant_id)}


def _upload(
    client: TestClient,
    business_id,
    tenant_id,
    *,
    kind="image",
    content=b"fake-image-bytes",
    content_type="image/png",
    filename="logo.png",
    category=None,
):
    data = {"kind": kind}
    if category:
        data["category"] = category
    return client.post(
        f"/businesses/{business_id}/assets/upload",
        headers=_headers(tenant_id),
        files={"file": (filename, io.BytesIO(content), content_type)},
        data=data,
    )


def test_upload_creates_a_real_asset_with_bytes_actually_persisted(
    client: TestClient, tenant: Tenant, business, tmp_path
):
    response = _upload(client, business.id, tenant.id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["origin"] == "uploaded"
    assert body["kind"] == "image"
    assert body["storage_url"].startswith("http://testserver/uploads/")
    assert body["original_filename"] == "logo.png"

    # The StaticFiles mount itself is wired up once at app-startup (see
    # app.main), before this test's local_storage_dir monkeypatch takes
    # effect — proving app.main's own routing is out of scope here (it's
    # exercised for real by whichever directory a real process starts
    # with). What this test owns: get_storage_provider (app.dependencies)
    # reads settings.local_storage_dir fresh on every request, so the
    # actual bytes really did land under the test's own throwaway
    # directory, not the real apps/api/var/uploads a developer might be
    # running against.
    storage_key = body["storage_url"].split("/uploads/", 1)[1]
    saved_path = tmp_path / "uploads" / storage_key
    assert saved_path.read_bytes() == b"fake-image-bytes"


def test_upload_rejects_a_content_type_not_allowed_for_the_kind(client: TestClient, tenant: Tenant, business):
    response = _upload(client, business.id, tenant.id, kind="logo", content_type="application/x-msdownload")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_asset_content_type"


def test_upload_rejects_a_file_over_the_configured_size_limit(client: TestClient, tenant: Tenant, business):
    oversized = b"x" * 2048  # settings.max_upload_size_bytes is patched to 1024 above

    response = _upload(client, business.id, tenant.id, content=oversized)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "asset_too_large"


def test_upload_rejects_an_empty_file(client: TestClient, tenant: Tenant, business):
    response = _upload(client, business.id, tenant.id, content=b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_asset_upload"


def test_upload_generates_a_safe_storage_key_not_the_original_filename(client: TestClient, tenant: Tenant, business):
    response = _upload(client, business.id, tenant.id, filename="../../etc/passwd.png")

    assert response.status_code == 201, response.text
    storage_url = response.json()["storage_url"]
    assert "../" not in storage_url
    assert "etc/passwd" not in storage_url
    # original_filename is preserved as metadata, not used as the path.
    assert response.json()["original_filename"] == "../../etc/passwd.png"


def test_upload_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    response = _upload(client, uuid.uuid4(), tenant.id)

    assert response.status_code == 404


def test_uploaded_asset_cannot_be_read_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    created = _upload(client, business.id, tenant.id)
    assert created.status_code == 201

    leaked = client.get(f"/businesses/{business.id}/assets", headers=_headers(other_tenant.id))
    assert leaked.status_code == 404


def test_uploaded_asset_cannot_be_deleted_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    created = _upload(client, business.id, tenant.id)
    asset_id = created.json()["id"]

    leaked_delete = client.delete(f"/businesses/{business.id}/assets/{asset_id}", headers=_headers(other_tenant.id))
    assert leaked_delete.status_code == 404

    still_there = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert len(still_there.json()) == 1


def test_owner_can_delete_their_own_uploaded_asset(client: TestClient, tenant: Tenant, business):
    created = _upload(client, business.id, tenant.id)
    asset_id = created.json()["id"]

    deleted = client.delete(f"/businesses/{business.id}/assets/{asset_id}", headers=_headers(tenant.id))
    assert deleted.status_code == 204

    listed = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert listed.json() == []


# --- multi-file batch upload (LR-01) --------------------------------------------


def _upload_batch(
    client: TestClient,
    business_id,
    tenant_id,
    files: list[tuple[str, bytes, str]],
    *,
    kind="image",
    category=None,
):
    data = {"kind": kind}
    if category:
        data["category"] = category
    return client.post(
        f"/businesses/{business_id}/assets/upload-batch",
        headers=_headers(tenant_id),
        files=[("files", (name, io.BytesIO(content), content_type)) for name, content, content_type in files],
        data=data,
    )


def test_batch_upload_creates_an_asset_per_file_in_one_request(client: TestClient, tenant: Tenant, business):
    files = [
        ("photo1.png", b"fake-image-bytes-1", "image/png"),
        ("photo2.png", b"fake-image-bytes-2", "image/png"),
        ("photo3.png", b"fake-image-bytes-3", "image/png"),
    ]

    response = _upload_batch(client, business.id, tenant.id, files, category="gallery")

    assert response.status_code == 207, response.text
    results = response.json()
    assert len(results) == 3
    assert all(result["success"] for result in results)
    assert [result["asset"]["original_filename"] for result in results] == ["photo1.png", "photo2.png", "photo3.png"]
    assert all(result["asset"]["category"] == "gallery" for result in results)

    listed = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert len(listed.json()) == 3


def test_batch_upload_preserves_successful_files_when_one_fails(client: TestClient, tenant: Tenant, business):
    files = [
        ("good1.png", b"real-bytes-1", "image/png"),
        ("bad.exe", b"not-an-image", "application/x-msdownload"),
        ("good2.png", b"real-bytes-2", "image/png"),
    ]

    response = _upload_batch(client, business.id, tenant.id, files)

    assert response.status_code == 207, response.text
    results = response.json()
    assert [r["success"] for r in results] == [True, False, True]
    assert results[1]["asset"] is None
    assert results[1]["error"]
    assert results[0]["asset"] is not None
    assert results[2]["asset"] is not None

    # The two good files are actually persisted, not rolled back because
    # of the bad one in the middle.
    listed = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert len(listed.json()) == 2


def test_batch_upload_for_unknown_business_is_404(client: TestClient, tenant: Tenant):
    response = _upload_batch(client, uuid.uuid4(), tenant.id, [("a.png", b"bytes", "image/png")])
    assert response.status_code == 404


def test_batch_uploaded_assets_cannot_be_read_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    files = [("a.png", b"bytes-a", "image/png"), ("b.png", b"bytes-b", "image/png")]
    created = _upload_batch(client, business.id, tenant.id, files)
    assert created.status_code == 207
    assert all(r["success"] for r in created.json())

    leaked = client.get(f"/businesses/{business.id}/assets", headers=_headers(other_tenant.id))
    assert leaked.status_code == 404


# --- Canonical storage identity (Phase 3 hotfix) --------------------------


def test_upload_records_canonical_storage_provider_and_key(client: TestClient, tenant: Tenant, business):
    response = _upload(client, business.id, tenant.id)

    body = response.json()
    assert body["storage_provider"] == "local"
    assert body["storage_key"] is not None
    assert body["storage_key"] in body["storage_url"]
    assert body["unavailable_reason"] is None


# --- Broken-asset detection (Phase 6 hotfix) -------------------------------


def test_verify_reports_no_unavailable_reason_for_a_real_present_file(client: TestClient, tenant: Tenant, business):
    created = _upload(client, business.id, tenant.id)
    asset_id = created.json()["id"]

    response = client.post(f"/businesses/{business.id}/assets/{asset_id}/verify", headers=_headers(tenant.id))

    assert response.status_code == 200
    assert response.json()["unavailable_reason"] is None


def test_verify_detects_a_db_row_whose_underlying_file_is_gone(
    client: TestClient, tenant: Tenant, business, tmp_path
):
    """The exact confirmed production bug this hotfix exists to catch:
    the BusinessAsset row survives, but Railway's ephemeral local disk
    did not — verify_business_asset must report that honestly."""
    created = _upload(client, business.id, tenant.id)
    body = created.json()
    storage_key = body["storage_url"].split("/uploads/", 1)[1]
    (tmp_path / "uploads" / storage_key).unlink()

    response = client.post(f"/businesses/{business.id}/assets/{body['id']}/verify", headers=_headers(tenant.id))

    assert response.status_code == 200
    assert response.json()["unavailable_reason"] == "Asset unavailable — please re-upload."

    # Persisted, not just returned once — a later reader (Studio, a
    # generation request) sees the same confirmed-broken state without
    # re-checking.
    listed = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert listed.json()[0]["unavailable_reason"] == "Asset unavailable — please re-upload."


def test_verify_for_unknown_asset_is_404(client: TestClient, tenant: Tenant, business):
    response = client.post(f"/businesses/{business.id}/assets/{uuid.uuid4()}/verify", headers=_headers(tenant.id))
    assert response.status_code == 404


def test_verify_cannot_be_run_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    created = _upload(client, business.id, tenant.id)
    asset_id = created.json()["id"]

    response = client.post(f"/businesses/{business.id}/assets/{asset_id}/verify", headers=_headers(other_tenant.id))
    assert response.status_code == 404


# --- Re-upload / replacement (Phase 7 hotfix) ------------------------------


def _replace(client: TestClient, business_id, asset_id, tenant_id, *, content=b"new-bytes", content_type="image/png"):
    return client.post(
        f"/businesses/{business_id}/assets/{asset_id}/replace",
        headers=_headers(tenant_id),
        files={"file": ("replacement.png", io.BytesIO(content), content_type)},
    )


def test_replace_repairs_the_same_asset_row_in_place(client: TestClient, tenant: Tenant, business, tmp_path):
    created = _upload(client, business.id, tenant.id)
    original = created.json()
    original_key = original["storage_url"].split("/uploads/", 1)[1]
    (tmp_path / "uploads" / original_key).unlink()  # simulate the lost Railway file

    response = _replace(client, business.id, original["id"], tenant.id)

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] == original["id"]  # same row — never a duplicate
    assert updated["kind"] == original["kind"]
    assert updated["category"] == original["category"]
    assert updated["storage_url"] != original["storage_url"]
    assert updated["unavailable_reason"] is None

    new_key = updated["storage_url"].split("/uploads/", 1)[1]
    assert (tmp_path / "uploads" / new_key).read_bytes() == b"new-bytes"

    # Only one row exists — the fix never created a second, orphaned asset.
    listed = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert len(listed.json()) == 1


def test_replace_deletes_the_old_object_when_it_still_existed(client: TestClient, tenant: Tenant, business, tmp_path):
    created = _upload(client, business.id, tenant.id)
    original = created.json()
    original_key = original["storage_url"].split("/uploads/", 1)[1]
    assert (tmp_path / "uploads" / original_key).exists()

    _replace(client, business.id, original["id"], tenant.id)

    assert not (tmp_path / "uploads" / original_key).exists()


def test_replace_rejects_a_content_type_not_allowed_for_the_existing_asset_kind(
    client: TestClient, tenant: Tenant, business
):
    created = _upload(client, business.id, tenant.id, kind="logo")

    response = _replace(client, business.id, created.json()["id"], tenant.id, content_type="application/x-msdownload")

    assert response.status_code == 415


def test_replace_for_unknown_asset_is_404(client: TestClient, tenant: Tenant, business):
    response = _replace(client, business.id, uuid.uuid4(), tenant.id)
    assert response.status_code == 404


def test_replace_cannot_be_run_through_another_tenant(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business
):
    created = _upload(client, business.id, tenant.id)
    asset_id = created.json()["id"]

    response = _replace(client, business.id, asset_id, other_tenant.id)
    assert response.status_code == 404

    still_broken = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert still_broken.json()[0]["id"] == asset_id  # untouched by the other tenant's attempt


# --- Storage provider failure mapping (hotfix: opaque 500 on /replace) ----
#
# Reproduces the exact production failure: a real, live R2 upload attempt
# whose underlying object write fails (bad credentials, wrong bucket,
# network error) must come back as one clean, structured AppError
# response — never an unmapped exception. See app.storage.errors and
# app.storage.r2.CloudflareR2StorageProvider.save's own try/except for the
# fix this reproduces.


class _AlwaysFailingStorageProvider(StorageProvider):
    """Stands in for a real StorageProvider whose underlying write fails —
    exactly what CloudflareR2StorageProvider.save now raises
    StorageProviderError for (bad credentials, wrong bucket, network
    error), without this test ever touching real R2 or credentials."""

    provider_name = "always-failing"

    def save(self, *, storage_key: str, content: bytes, content_type: str | None = None) -> StoredFile:
        raise StorageProviderError("simulated R2 failure: SignatureDoesNotMatch")

    def delete(self, storage_key: str) -> None:
        pass

    def exists(self, storage_key: str) -> bool:
        return False

    def presigned_url(self, storage_key: str, *, expires_in_seconds: int) -> str | None:
        return None

    def load(self, storage_key: str) -> bytes:
        raise StorageProviderError("simulated R2 failure")

    def url_path(self, storage_key: str) -> str:
        return f"/uploads/{storage_key}"


@pytest.fixture()
def failing_storage_client(client: TestClient):
    """Same `client` fixture as every other test in this module, with the
    real (Local) storage provider swapped for one whose save() always
    raises StorageProviderError — the one extra override needed to
    reproduce the production /replace 500 without real R2 credentials."""
    app.dependency_overrides[get_storage_provider] = lambda: _AlwaysFailingStorageProvider()
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_storage_provider, None)


def test_upload_maps_a_storage_provider_failure_to_a_clean_502(failing_storage_client: TestClient, tenant, business):
    response = _upload(failing_storage_client, business.id, tenant.id)

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "storage_provider_error"

    # No half-created row — a failed upload must never leave an
    # asset pointing at an object that was never actually written.
    listed = failing_storage_client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    assert listed.json() == []


def test_replace_maps_a_storage_provider_failure_to_a_clean_502_and_leaves_the_row_untouched(
    client: TestClient, tenant: Tenant, business
):
    # Upload succeeds normally first (real local storage), then the
    # provider is swapped to the always-failing one only for the replace
    # attempt — mirrors the production sequence: an existing, working
    # asset row, then one failed re-upload attempt against it.
    created = _upload(client, business.id, tenant.id)
    original = created.json()

    app.dependency_overrides[get_storage_provider] = lambda: _AlwaysFailingStorageProvider()
    try:
        response = _replace(client, business.id, original["id"], tenant.id)
    finally:
        app.dependency_overrides.pop(get_storage_provider, None)

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "storage_provider_error"

    # The exact "so we don't create orphan objects" guarantee: a failed
    # replace must never touch the existing row's storage fields — same
    # provider/key/url as before the failed attempt, not half-updated.
    still_there = client.get(f"/businesses/{business.id}/assets", headers=_headers(tenant.id))
    unchanged = still_there.json()[0]
    assert unchanged["id"] == original["id"]
    assert unchanged["storage_provider"] == original["storage_provider"]
    assert unchanged["storage_key"] == original["storage_key"]
    assert unchanged["storage_url"] == original["storage_url"]
