"""A8.1.2 — create_website_draft through the REAL chain, no fake build:

    SiteConfigPayload -> create_website_draft -> real `astro build`
    (apps/site-builder) -> PlatformContract

test_website_draft_service.py fakes build_site (fast, by design), which is
exactly why the block-metadata stripping bug (SiteBlockPayload dropping
`id`/`background`/`reveal`) shipped: no test ever built a real
generator-shaped config and ran PlatformContract over the result. This
module does, with the same deterministic reforma fixture
test_site_builder_integration.py uses — local only, no external provider.

`build_site` is wrapped (never replaced) so the real artifact can also be
inspected and compared against what A8.3.4.1 stores for publishing."""

import copy
import json
import re
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.enums import WebsiteDraftStatus
from app.publishing import build as build_module
from app.publishing.artifact_store import artifact_sha256, load_draft_artifact
from app.publishing.drafts import create_website_draft
from app.schemas.site_config import SiteConfigPayload
from app.storage import LocalStorageProvider

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reforma_site_config.json"
_SECTION = re.compile(r"<section\b[^>]*>")


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _section_tag(html: str, section_id: str) -> str:
    return next(tag for tag in _SECTION.findall(html) if f'id="{section_id}"' in tag)


@pytest.fixture()
def built_artifacts(monkeypatch: pytest.MonkeyPatch) -> list:
    artifacts: list = []

    def real_build_and_record(site_config):
        artifact = build_module.build_site(site_config)
        artifacts.append(artifact)
        return artifact

    monkeypatch.setattr("app.publishing.drafts.build_site", real_build_and_record)
    return artifacts


def test_a_valid_generator_config_builds_ready_with_every_anchor_resolved(
    session: Session, tenant: Tenant, business: Business, built_artifacts: list, tmp_path
):
    raw = _fixture()
    blocks = {block["id"]: block for block in raw["pages"][0]["blocks"]}
    # The fixture already carries hero -> #contact / #services and the
    # services/contact ids; add the presentational metadata too, so one
    # real build proves all three BlockConfigBase fields reach the output.
    blocks["services"]["background"] = "surface"
    blocks["about"]["reveal"] = False

    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=SiteConfigPayload.model_validate(raw),
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        storage=LocalStorageProvider(root_dir=tmp_path / "storage"),
    )

    assert draft.build_error is None
    assert draft.status is WebsiteDraftStatus.READY
    assert not any("PlatformContract:broken_anchor_target" in issue for issue in draft.validation_issues or [])

    # A8.3.4.1 on a REAL astro build: the stored artifact is byte-for-byte
    # the one build that ran (security headers included), hash-verified.
    assert len(built_artifacts) == 1
    stored = load_draft_artifact(
        LocalStorageProvider(root_dir=tmp_path / "storage"),
        storage_key=draft.artifact_key,
        expected_sha256=draft.artifact_sha256,
        draft_id=draft.id,
    )
    assert stored.files == built_artifacts[0].files
    assert "_headers" in stored.files
    assert artifact_sha256(stored) == artifact_sha256(built_artifacts[0]) == draft.artifact_sha256

    html = built_artifacts[0].files["index.html"].decode("utf-8")
    anchors = set(re.findall(r'href="#([\w-]+)"', html))
    assert {"contact", "services"} <= anchors
    for target in anchors:
        assert f'id="{target}"' in html

    # id: every generated section renders its own anchor id.
    rendered_ids = [re.search(r'id="([\w-]+)"', tag).group(1) for tag in _SECTION.findall(html) if "id=" in tag]
    assert {"hero", "services", "about", "cta", "contact"} <= set(rendered_ids)
    # background: "surface" reaches the section's data-surface hook.
    assert 'data-surface="surface"' in _section_tag(html, "services")
    # reveal: false opts the section out of the scroll-reveal class;
    # an omitted reveal keeps the block's own default (true).
    assert "block-reveal" not in _section_tag(html, "about")
    assert "block-reveal" in _section_tag(html, "services")

    # The stored draft config is the same metadata-preserving shape.
    stored = {block["id"]: block for block in draft.site_config["pages"][0]["blocks"]}
    assert stored["services"]["background"] == "surface"
    assert stored["about"]["reveal"] is False


def test_platform_contract_still_blocks_a_genuinely_broken_anchor(
    session: Session, tenant: Tenant, business: Business, built_artifacts: list, tmp_path
):
    raw = copy.deepcopy(_fixture())
    contact = next(block for block in raw["pages"][0]["blocks"] if block["type"] == "contact")
    del contact["id"]  # hero/CTA still link to #contact — now genuinely dangling.

    draft = create_website_draft(
        session=session,
        tenant_id=tenant.id,
        business_id=business.id,
        site_config=SiteConfigPayload.model_validate(raw),
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        storage=LocalStorageProvider(root_dir=tmp_path / "storage"),
    )

    assert draft.status is WebsiteDraftStatus.BUILD_FAILED
    assert draft.artifact_key is None and draft.artifact_sha256 is None  # never stored as publishable
    assert not (tmp_path / "storage").exists() or not any((tmp_path / "storage").rglob("*.gz"))
    assert 'An anchor targets "#contact"' in draft.build_error
    assert '"#services"' not in draft.build_error
