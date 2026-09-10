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
from app.dependencies import get_session
from app.main import app


@pytest.fixture()
def client(session, tmp_path, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    # Every test gets its own throwaway upload directory — never the
    # real apps/api/var/uploads a developer might be running against.
    monkeypatch.setattr(settings, "local_storage_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "max_upload_size_bytes", 1024)

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


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
