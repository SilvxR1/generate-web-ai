"""R5: a supervised import's Visual QA runs with no network, so the business
assets its plan embeds by URL (the brand policy's owner-approved logo) must be
handed to the worker as bytes — exactly those, never the rest of the gallery.
Without them the logo is a broken image and Visual QA fails the artifact."""

import json

from app.db.models.business_asset import BusinessAsset
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin
from app.storage.local import LocalStorageProvider
from app.worker import intake


def _asset(session, business, storage, name: str, content: bytes) -> BusinessAsset:
    key = f"{business.id}/{name}"
    storage.save(storage_key=key, content=content)
    row = BusinessAsset(
        tenant_id=business.tenant_id,
        business_id=business.id,
        kind=AssetKind.IMAGE,
        category=AssetCategory.GALLERY,
        origin=AssetOrigin.UPLOADED,
        storage_key=key,
        storage_url=f"https://assets.example/{key}",
    )
    session.add(row)
    session.flush()
    return row


def test_only_the_assets_the_plan_references_are_handed_to_offline_visual_qa(session, business, tmp_path):
    storage = LocalStorageProvider(root_dir=tmp_path)
    logo = _asset(session, business, storage, "logo.jpg", b"logo-bytes")
    gallery = _asset(session, business, storage, "gallery.jpg", b"gallery-bytes")
    plan_text = json.dumps({"brand": {"logo_url": logo.storage_url}})

    assets = intake._referenced_assets(session, business.tenant_id, business.id, storage, plan_text)

    assert assets == {logo.storage_url: b"logo-bytes"}
    assert gallery.storage_url not in assets


def test_a_plan_without_business_asset_urls_sends_no_assets(session, business, tmp_path):
    storage = LocalStorageProvider(root_dir=tmp_path)
    _asset(session, business, storage, "logo.jpg", b"logo-bytes")

    assert intake._referenced_assets(session, business.tenant_id, business.id, storage, "{}") == {}
