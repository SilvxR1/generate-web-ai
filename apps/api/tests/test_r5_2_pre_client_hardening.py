# ruff: noqa: F811 — pytest fixtures imported from the R5 / A8 suites
"""R5.2 — pre-client hardening, found by the Lumen/Nexo production runs:

1. a source whose declared identity contradicts BusinessTruth (the Lumen
   export uploaded under Nexo) needs an explicit human decision to build;
3. a wrong/superseded import can be discarded — audited, never deleted;
4. silent spam drops are logged by reason only; a Private Preview form
   submission records only a per-draft count/time (never a lead);
5. every web app manifest is validated on the exact artifact bytes;
6. a supervised artifact carries its contract/QA verdicts, tied to its SHA.
"""

import json
import os
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.creative.source_adapter.facts import FactBinding, FactDiscovery
from app.creative.source_adapter.fixtures import nexo_reformas_business_config
from app.creative.source_adapter.identity import assess_identity, declarations
from app.creative.source_adapter.plan import VirtualTree
from app.creative.source_adapter.preview import serve_artifact
from app.db.models.business import Business
from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.db.models.lead import Lead
from app.db.models.source_import import SourceImport, SourceImportEvent
from app.domain.business_truth import derive_business_truth
from app.domain.enums import BusinessStatus, BusinessVertical
from app.publishing.publisher import WebsiteArtifact
from app.qa.web_manifest import manifest_links, validate_web_manifests
from tests.test_a8_real_draft_preview import (  # noqa: F401 — shared fixtures/helpers
    _counts,
    _lead_payload,
    builds,
    public_client,
    storage,
)
from tests.test_a8_real_draft_preview import _ready as _deterministic_ready
from tests.test_r5_source_imports import (  # noqa: F401 — shared fixtures/helpers
    Built,
    Env,
    _draft_url,
    _import_and_build,
    _ready,
    _replace,
    _state,
    _submit,
    _tampered,
    _variant_zip,
    built,
    env,
)

NEXO_EXPORT = Path(os.environ.get("GWA_NEXO_EXPORT_ZIP", "/mnt/c/Users/Usuario/Downloads/nexo-reformas-web.zip"))


# --- 1. Source <-> BusinessTruth identity ----------------------------------------------------------


def _tree(files: dict[str, str]) -> VirtualTree:
    return VirtualTree({path: text.encode() for path, text in files.items()})


def _facts(*bound: str) -> FactDiscovery:
    return FactDiscovery([FactBinding(f, f, f, []) for f in bound], [], [], {})


NEXO_TRUTH = derive_business_truth(business_config=nexo_reformas_business_config())
LUMEN_DECLARED = {
    "src/app-meta.json": json.dumps({"og_title": "Lumen Physio — Physiotherapy in Lisbon"}),
    "src/routes/__root.tsx": '{ property: "og:site_name", content: "Lumen Physio" },',
}


def test_strong_contradiction_needs_a_human_decision():
    findings = assess_identity(_tree(LUMEN_DECLARED), NEXO_TRUTH, _facts(), app_meta_file="src/app-meta.json")
    assert [(f["code"], f["severity"], f["subject"]) for f in findings] == [
        ("source_identity_conflict", "review", "Lumen Physio")
    ]
    detail = findings[0]["detail"]
    assert "'Lumen Physio'" in detail and "'Nexo Reformas'" in detail  # both sides, quoted
    assert "src/app-meta.json og_title" in detail and "og:site_name" in detail  # where the evidence is


def test_absent_or_generic_identity_evidence_never_raises_a_finding():
    assert assess_identity(_tree({"src/x.tsx": "export const a = 1"}), NEXO_TRUTH, _facts(), app_meta_file=None) == []
    generic = {"src/app-meta.json": json.dumps({"og_title": "Home | Official site"})}
    assert declarations(_tree(generic), app_meta_file="src/app-meta.json") == []
    assert assess_identity(_tree(generic), NEXO_TRUTH, _facts(), app_meta_file="src/app-meta.json") == []


def test_compatible_identity_including_a_restyled_name_is_accepted():
    restyled = {"public/site.webmanifest": json.dumps({"name": "NEXO · Reformas Valencia"})}
    assert assess_identity(_tree(restyled), NEXO_TRUTH, _facts(), app_meta_file=None) == []
    # BusinessTruth's name presented anywhere in the text is enough.
    assert assess_identity(_tree(LUMEN_DECLARED), NEXO_TRUTH, _facts("identity.name"), app_meta_file=None) == []


def test_another_name_with_some_truth_facts_present_is_only_informational():
    one_declaration = {"public/site.webmanifest": json.dumps({"name": "Casa Nova"})}
    findings = assess_identity(
        _tree(one_declaration), NEXO_TRUTH, _facts("location.city", "services.cocina"), app_meta_file=None
    )
    assert [(f["code"], f["severity"]) for f in findings] == [("source_identity_unconfirmed", "info")]


def _nexo_business(env: Env) -> Business:
    business = Business(
        tenant_id=env.tenant.id,
        name="Nexo Reformas (R5.2 fixture)",
        slug="nexo-r52",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Fictional R5.2 business.",
        status=BusinessStatus.DRAFT,
        config=nexo_reformas_business_config().model_dump(mode="json"),
    )
    env.session.add(business)
    env.session.flush()
    return business


def test_the_lumen_export_under_nexo_cannot_build_until_a_human_approves_the_mismatch(env: Env, tmp_path):
    nexo = _nexo_business(env)
    base = f"/businesses/{nexo.id}/source-imports"
    created = env.client.post(
        base, headers=env.headers, files={"file": ("lumen.zip", _variant_zip(tmp_path, "wrong"), "application/zip")}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    conflict = "source_identity_conflict:Lumen Physio"
    assert body["status"] == "needs_review" and conflict in body["open_reviews"]
    assert env.client.post(f"{base}/{body['id']}/build", headers=env.headers).status_code == 409
    decided = env.client.post(
        f"{base}/{body['id']}/decisions",
        headers=env.headers,
        json={"finding_id": conflict, "decision": "approved", "rationale": "Test: deliberate mismatch fixture."},
    )
    assert decided.status_code == 200 and decided.json()["status"] == "ready_to_build"
    assert [d["finding_id"] for d in decided.json()["decisions"]] == [conflict]  # audited, bound to this plan


def test_the_lumen_export_under_its_own_business_has_no_identity_finding(env: Env, tmp_path):
    created = env.upload(_variant_zip(tmp_path, "own"))
    assert created.status_code == 201
    assert not [f for f in created.json()["inspection"]["findings"] if f["code"].startswith("source_identity")]
    assert created.json()["status"] == "ready_to_build"


@pytest.mark.skipif(not NEXO_EXPORT.is_file(), reason="the real Nexo export is not available on this machine")
def test_the_real_nexo_export_under_nexo_has_no_identity_finding_and_an_unchanged_plan(tmp_path):
    from app.creative.source_adapter.pipeline import plan_export

    planned = plan_export(
        NEXO_EXPORT, tmp_path / "w", nexo_reformas_business_config(), site_origin="https://nexo-reformas.example"
    )
    assert not [f for f in planned.supportability.findings if f.code.startswith("source_identity")]
    # The plan identity recorded before R5.2: legitimate sources are unaffected.
    assert planned.plan is not None
    assert planned.plan.plan_sha256 == "2802d4d1c492ab204bfaf7887a1274849d4a5902558e2fe233870bbc83651cb3"


# --- 3. Discard ------------------------------------------------------------------------------------


def _discard(env: Env, import_id: str, reason: str = "Wrong export for this business"):
    return env.client.post(env.url(f"/{import_id}/discard"), headers=env.headers, json={"reason": reason})


def test_discard_is_audited_keeps_everything_and_ends_every_action(env: Env, tmp_path):
    body = env.upload(_variant_zip(tmp_path, "discard")).json()
    blank = env.client.post(env.url(f"/{body['id']}/discard"), headers=env.headers, json={"reason": "  "})
    assert blank.status_code == 422
    discarded = _discard(env, body["id"])
    assert discarded.status_code == 200, discarded.text
    state = discarded.json()
    assert (state["status"], state["stage"]) == ("discarded", "discarded")
    [event] = state["events"]
    assert event["kind"] == "discarded" and event["reason"] == "Wrong export for this business"
    assert event["previous_status"] == "ready_to_build" and event["snapshot_sha256"] == body["zip_sha256"]
    assert event["actor_email"] == env.user.email
    for action in ("reinspect", "build"):
        assert env.client.post(env.url(f"/{body['id']}/{action}"), headers=env.headers).status_code == 409, action
    decision = {"finding_id": "x", "decision": "approved", "rationale": "no"}
    assert env.client.post(env.url(f"/{body['id']}/decisions"), headers=env.headers, json=decision).status_code == 409
    assert _discard(env, body["id"]).status_code == 409  # already discarded
    # Nothing deleted: the row, the immutable snapshot and the audit event remain.
    row = env.session.get(SourceImport, uuid.UUID(body["id"]))
    assert row is not None and env.storage.exists(row.snapshot_key)
    assert env.session.query(SourceImportEvent).filter_by(source_import_id=row.id).count() == 1
    listed = env.client.get(env.url(), headers=env.headers).json()
    assert [(i["id"], i["stage"]) for i in listed] == [(body["id"], "discarded")]  # still visible (history)


def test_a_building_import_cannot_be_discarded(env: Env, built: Built):
    body, _job, _token = _import_and_build(env, built.zip_bytes)
    assert _discard(env, body["id"]).status_code == 409


def test_a_discarded_imports_artifact_can_never_be_approved(env: Env, built: Built):
    state = _ready(env, built)
    assert _discard(env, state["id"]).status_code == 200
    draft = _state(env, state["id"])["draft"]
    assert any("discarded" in p for p in draft["gate_problems"])
    approve = env.client.post(_draft_url(env, draft["id"], "approve"), headers=env.headers)
    assert approve.status_code >= 400 and env.publisher.artifacts == []


def test_an_approved_imports_import_cannot_be_discarded(env: Env, built: Built):
    state = _ready(env, built)
    draft_id = state["draft"]["id"]
    assert env.client.post(_draft_url(env, draft_id, "approve"), headers=env.headers).status_code == 200
    assert _discard(env, state["id"]).status_code == 409


# --- 4. Private Preview form signal and spam logging ----------------------------------------------


PREVIEW_HOST = "abc12345.gwa-draft-previews.pages.dev"


def test_spam_drops_are_logged_by_reason_only(public_client: TestClient, session: Session, business: Business, caplog):
    caplog.set_level("INFO")
    url = f"/public/businesses/{business.id}/leads"
    honeypot = public_client.post(url, json={**_lead_payload(), "company_website": "http://bot.example"})
    too_fast = public_client.post(url, json={**_lead_payload(), "rendered_at": datetime.now(UTC).isoformat()})
    assert honeypot.status_code == too_fast.status_code == 201  # same response as a real success
    assert _counts(session, business)[0] == 0
    assert f"public_lead_suppressed_spam business={business.id} reason=honeypot" in caplog.text
    assert f"public_lead_suppressed_spam business={business.id} reason=too_fast" in caplog.text
    lowered = caplog.text.lower()
    assert "maria" not in lowered and "presupuesto" not in lowered and "bot.example" not in lowered


def test_a_preview_submission_counts_on_its_draft_and_stores_nothing_else(
    public_client: TestClient, session: Session, tenant, business: Business, storage, builds, caplog
):
    draft = _deterministic_ready(session, tenant, business, storage)
    draft.preview_url = f"https://{PREVIEW_HOST}/"
    session.flush()
    caplog.set_level("INFO")
    url = f"/public/businesses/{business.id}/leads"
    for _ in range(2):
        response = public_client.post(url, json=_lead_payload(), headers={"Origin": f"https://{PREVIEW_HOST}"})
        assert response.status_code == 201
    session.refresh(draft)
    assert draft.preview_form_submissions == 2 and draft.preview_form_last_at is not None
    assert _counts(session, business) == (0, 0, 0)  # no lead, no notification, no analytics
    assert f"public_lead_suppressed_preview business={business.id} draft={draft.id}" in caplog.text
    assert "maria" not in caplog.text.lower()
    # Another preview host (not this draft's) records nothing; production still creates a real lead.
    public_client.post(url, json=_lead_payload(), headers={"Origin": "https://zzz.gwa-draft-previews.pages.dev"})
    public_client.post(url, json=_lead_payload(), headers={"Origin": "https://cositasypuntos.com"})
    session.refresh(draft)
    assert draft.preview_form_submissions == 2
    assert session.query(Lead).filter_by(business_id=business.id).count() == 1


# --- 5. Web app manifest ---------------------------------------------------------------------------


def _site(manifest: str | None, *, link: str = '<link rel="manifest" href="/site.webmanifest"/>') -> dict[str, bytes]:
    files = {"index.html": f"<html><head>{link}</head><body></body></html>".encode(), "icon-192.png": b"\x89PNG"}
    if manifest is not None:
        files["site.webmanifest"] = manifest.encode()
    return files


GOOD = json.dumps({"name": "Nexo", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]})


def test_a_valid_manifest_passes_and_no_manifest_is_fine():
    assert validate_web_manifests(_site(GOOD)) == []
    assert validate_web_manifests({"index.html": b"<html></html>"}) == []
    assert manifest_links(_site(GOOD)) == [("index.html", "/site.webmanifest")]


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        (_site(None), "does not exist"),
        (_site("{not json"), "not valid JSON"),
        (_site("[1, 2]"), "not a JSON object"),
        (_site(json.dumps({"icons": [{"src": "/missing.png"}]})), "icon /missing.png does not exist"),
        (_site(json.dumps({"icons": [{"src": "https://cdn.example/i.png"}]})), "is not same-origin"),
        (_site(GOOD, link='<link rel="manifest" href="https://evil.example/m.json">'), "not same-origin"),
        (_site(GOOD, link='<link rel="manifest" href="//evil.example/m.json">'), "not same-origin"),
        (_site(GOOD, link='<link rel="manifest" href="data:application/json,{}">'), "not same-origin"),
        (
            {**_site(GOOD), "_headers": b"/site.webmanifest\n  Content-Type: text/html\n"},
            "_headers serves the manifest as 'text/html'",
        ),
    ],
)
def test_invalid_or_unsafe_manifests_are_reported(files, expected):
    problems = validate_web_manifests(files)
    assert problems and any(expected in p for p in problems), problems


def test_the_local_qa_server_serves_the_manifest_as_application_manifest_json():
    with serve_artifact(WebsiteArtifact(files=_site(GOOD), entry_point="index.html")) as origin:
        with urllib.request.urlopen(f"{origin}/site.webmanifest", timeout=10) as response:  # noqa: S310 — loopback
            assert response.status == 200
            assert response.headers["Content-Type"].split(";")[0] == "application/manifest+json"
            assert json.loads(response.read())["name"] == "Nexo"


def test_a_candidate_with_a_broken_manifest_is_refused_by_intake(env: Env, built: Built):
    body, job, token = _import_and_build(env, built.zip_bytes)
    link = b'<link rel="manifest" href="/gone.webmanifest"></head>'
    broken = _tampered(built.result, _replace("index.html", b"</head>", link))
    assert _submit(env, job, token, broken).status_code == 204
    state = _state(env, body["id"])
    assert state["status"] == "build_failed" and "Web app manifest invalid" in (state["error"] or "")


# --- 6. Contract/QA summary on the artifact --------------------------------------------------------


def _artifact_row(env: Env, draft_id: str) -> GenerativeWebsiteArtifact:
    return env.session.query(GenerativeWebsiteArtifact).filter_by(website_draft_id=uuid.UUID(draft_id)).one()


def test_a_supervised_artifact_records_its_verdicts_tied_to_its_sha(env: Env, built: Built):
    state = _ready(env, built)
    draft = state["draft"]
    qa = _artifact_row(env, draft["id"]).qa_state
    assert qa["summary_version"] == 1 and qa["artifact_sha256"] == draft["artifact_sha256"]
    assert qa["passed"] is True and qa["blocking_violations"] == []
    assert qa["platform_contract"]["passed"] is True and qa["platform_contract"]["version"]
    assert qa["truth_contract"]["passed"] is True and qa["truth_contract"]["version"]
    assert qa["web_manifest"]["passed"] is True
    assert qa["visual_qa"]["artifact_sha256"] == draft["artifact_sha256"]
    assert len(json.dumps(qa)) < 8000  # references and rule ids, not evidence blobs


def test_historical_artifacts_with_an_empty_qa_state_stay_readable(env: Env, built: Built):
    state = _ready(env, built)
    _artifact_row(env, state["draft"]["id"]).qa_state = {}
    env.session.flush()
    assert _state(env, state["id"])["draft"]["status"] == "ready"
    response = env.client.get(_draft_url(env, state["draft"]["id"], "generative-artifact"), headers=env.headers)
    assert response.status_code == 200 and response.json()["qa_state"] == {}


def test_the_draft_state_exposes_the_preview_form_signal(env: Env, built: Built):
    state = _ready(env, built)
    assert state["draft"]["preview_form_submissions"] == 0 and state["draft"]["preview_form_last_at"] is None
