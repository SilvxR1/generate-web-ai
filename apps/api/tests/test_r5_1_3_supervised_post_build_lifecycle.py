# ruff: noqa: F811 — pytest fixtures imported from the R5 / R5.1.1 suites
"""R5.1.3 — supervised post-build lifecycle.

The runbook closes scoped supervised-import access as soon as the build job
exists. Closing WRITE access must stop every new supervised mutation, but it
must not hide the import that already exists, its draft or its artifact:
the owner still has to see the build finish and preview the exact result.
Read access is never wider than the caller's own tenant and business.
"""

import uuid

from fastapi.testclient import TestClient

from app.db.models.generation_job import GenerationJob
from app.db.models.source_import import SourceImport
from app.domain.enums import GenerationJobStatus
from app.main import app
from app.publishing.artifact_store import artifact_sha256
from tests.test_r5_1_1_scoped_supervised_imports import (  # noqa: F401 — shared fixtures/helpers
    READS,
    WRITES,
    _business,
    _call,
    _capability,
    _login,
    _scope,
    two_tenants,
)
from tests.test_r5_source_imports import (  # noqa: F401 — shared fixtures/helpers
    Built,
    Env,
    _draft_url,
    _submit,
    _variant_zip,
    built,
    env,
)


def _import(env: Env, tmp_path, name: str = "existing") -> uuid.UUID:
    created = env.upload(_variant_zip(tmp_path, name))
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


def _counts(env: Env) -> tuple[int, int]:
    return (
        env.session.query(SourceImport).count(),
        env.session.query(GenerationJob).count(),
    )


# --- Read-only access to EXISTING imports once write access is closed ------------------------------


def test_gate_off_existing_import_stays_readable(env: Env, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    import_id = _import(env, tmp_path)
    _scope(monkeypatch)  # write access closed: global off, allowlist empty
    listed = _call(env.client, env.business.id, "list", env.headers)
    assert listed.status_code == 200 and [i["id"] for i in listed.json()] == [str(import_id)]
    got = _call(env.client, env.business.id, "get", env.headers, import_id)
    assert got.status_code == 200 and got.json()["zip_sha256"] and got.json()["inspection"]["findings"] is not None
    diagnostics = _call(env.client, env.business.id, "diagnostics", env.headers, import_id)
    assert diagnostics.status_code == 200 and diagnostics.json()["plan_sha256"] == got.json()["plan_sha256"]


def test_gate_off_every_mutation_is_refused_and_nothing_changes(env: Env, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    import_id = _import(env, tmp_path)
    before = env.client.get(env.url(f"/{import_id}"), headers=env.headers).json()
    _scope(monkeypatch)
    counts = _counts(env)
    for route in WRITES:
        response = _call(env.client, env.business.id, route, env.headers, import_id)
        assert response.status_code == 403 and response.json()["error"]["code"] == "feature_not_available", route
    upload = env.upload(_variant_zip(tmp_path, "second"))
    assert upload.status_code == 403  # a real, valid export is refused too
    assert _counts(env) == counts  # no import, no job
    after = env.client.get(env.url(f"/{import_id}"), headers=env.headers).json()
    assert (after["status"], after["plan_sha256"], after["decisions"]) == (
        before["status"],
        before["plan_sha256"],
        before["decisions"],
    )


def test_reads_never_create_or_mutate_workflow_state(env: Env, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    import_id = _import(env, tmp_path)
    _scope(monkeypatch)
    counts = _counts(env)
    for _ in range(3):
        for route in READS:
            assert _call(env.client, env.business.id, route, env.headers, import_id).status_code == 200
    assert _counts(env) == counts
    assert env.session.get(SourceImport, import_id).status.value == "ready_to_build"  # type: ignore[union-attr]


def test_a_business_that_never_had_imports_is_not_opened_by_the_read_gate(env: Env, monkeypatch, tmp_path):
    neighbour = _business(env, env.tenant.id, "never-imported")
    _scope(monkeypatch, allow=f"{env.business.id}")
    _import(env, tmp_path)  # the env business HAS an import...
    _scope(monkeypatch)
    for route in READS + WRITES:  # ...which never opens the neighbour, even in the same tenant
        response = _call(env.client, neighbour.id, route, env.headers)
        assert response.status_code == 403 and response.json()["error"]["code"] == "feature_not_available", route


def test_an_import_is_never_readable_through_another_businesss_path(env: Env, monkeypatch, tmp_path):
    other = _business(env, env.tenant.id, "has-its-own")
    _scope(monkeypatch, allow=f"{env.business.id},{other.id}")
    mine = _import(env, tmp_path, "a")
    theirs = uuid.UUID(
        env.client.post(
            f"/businesses/{other.id}/source-imports",
            headers=env.headers,
            files={"file": ("b.zip", _variant_zip(tmp_path, "b"), "application/zip")},
        ).json()["id"]
    )
    _scope(monkeypatch)
    for route in ("get", "diagnostics"):
        assert _call(env.client, other.id, route, env.headers, mine).status_code == 404, route
        assert _call(env.client, env.business.id, route, env.headers, theirs).status_code == 404, route
    listed = _call(env.client, other.id, "list", env.headers).json()
    assert [i["id"] for i in listed] == [str(theirs)]


def test_another_tenant_can_never_read_existing_imports(env: Env, two_tenants, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    owner = TestClient(app)
    csrf = _login(owner, env.user.email, two_tenants["password"])
    created = owner.post(
        f"/businesses/{env.business.id}/source-imports",
        headers={"X-Tenant-Id": str(env.tenant.id), "X-CSRF-Token": csrf},
        files={"file": ("a.zip", _variant_zip(tmp_path, "real"), "application/zip")},
    )
    assert created.status_code == 201, created.text
    import_id = uuid.UUID(created.json()["id"])
    _scope(monkeypatch)

    owner_headers = {"X-Tenant-Id": str(env.tenant.id), "X-CSRF-Token": csrf}
    assert _call(owner, env.business.id, "get", owner_headers, import_id).status_code == 200  # real auth, read-only

    outsider = TestClient(app)
    csrf_b = _login(outsider, two_tenants["outsider"].email, two_tenants["password"])
    claiming_a = {"X-Tenant-Id": str(env.tenant.id), "X-CSRF-Token": csrf_b}
    own_tenant = {"X-Tenant-Id": str(two_tenants["tenant_b"].id), "X-CSRF-Token": csrf_b}
    for route in READS:
        assert _call(outsider, env.business.id, route, claiming_a, import_id).status_code == 404, route
        assert _call(outsider, env.business.id, route, own_tenant, import_id).status_code in (403, 404), route
    anonymous = TestClient(app)
    for route in READS:
        assert (
            _call(anonymous, env.business.id, route, {"X-Tenant-Id": str(env.tenant.id)}, import_id).status_code == 401
        )


# --- Capability ---------------------------------------------------------------------------------


def test_capability_reports_write_read_only_and_disabled(env: Env, monkeypatch, tmp_path):
    empty = _business(env, env.tenant.id, "empty")
    _scope(monkeypatch, allow=f"{env.business.id}")
    write = _capability(env, env.business.id)
    assert (write["mode"], write["write_enabled"], write["read_enabled"], write["enabled"], write["access"]) == (
        "write",
        True,
        True,
        True,
        "scoped",
    )
    _import(env, tmp_path)
    _scope(monkeypatch)
    read_only = _capability(env, env.business.id)
    assert (read_only["mode"], read_only["write_enabled"], read_only["read_enabled"], read_only["enabled"]) == (
        "read_only",
        False,
        True,
        False,
    )
    assert read_only["access"] == "disabled"
    disabled = _capability(env, empty.id)
    assert (disabled["mode"], disabled["write_enabled"], disabled["read_enabled"], disabled["enabled"]) == (
        "disabled",
        False,
        False,
        False,
    )
    _scope(monkeypatch, global_on=True)
    assert _capability(env, empty.id)["mode"] == "write"


def test_capability_never_reveals_the_allowlist_in_any_mode(env: Env, monkeypatch, tmp_path):
    neighbour = uuid.uuid4()
    _scope(monkeypatch, allow=f"{env.business.id},{neighbour}")
    _import(env, tmp_path)
    for allow in (f"{env.business.id},{neighbour}", f"{neighbour}", ""):
        _scope(monkeypatch, allow=allow)
        text = env.client.get(env.url("/capability"), headers=env.headers).text
        assert str(neighbour) not in text and "business_ids" not in text and "allowlist" not in text


# --- Preview after write access is closed ---------------------------------------------------------


def test_preview_works_for_a_ready_supervised_draft_after_access_is_closed(env: Env, monkeypatch, built: Built):
    _scope(monkeypatch, allow=f"{env.business.id}")
    created = env.upload(built.zip_bytes)
    assert created.status_code == 201, created.text
    import_id = created.json()["id"]
    assert env.client.post(env.url(f"/{import_id}/build"), headers=env.headers).status_code == 202
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    job = env.session.get(GenerationJob, uuid.UUID(claim.json()["request"]["job_id"]))
    assert job is not None
    assert _submit(env, job, claim.json()["job_token"], built.result).status_code == 204
    _scope(monkeypatch)  # closed AFTER the build: preview must not need write access
    state = env.client.get(env.url(f"/{import_id}"), headers=env.headers).json()
    draft = state["draft"]
    assert draft["status"] == "ready"
    preview = env.client.post(_draft_url(env, draft["id"], "preview"), headers=env.headers)
    assert preview.status_code == 200, preview.text
    assert artifact_sha256(env.preview.deployed[-1]) == draft["artifact_sha256"]
    assert env.client.get(env.url(f"/{import_id}"), headers=env.headers).json()["draft"]["status"] == "ready"


# --- The intended lifecycle, end to end -----------------------------------------------------------


def test_scoped_import_build_close_access_then_observe_ready_and_preview(env: Env, monkeypatch, built: Built):
    """scoped access -> import -> build -> job exists -> access removed ->
    job completes -> import readable -> READY -> preview of the exact artifact.
    No approval, no publish."""
    _scope(monkeypatch, allow=f"{env.business.id}")
    created = env.upload(built.zip_bytes)
    assert created.status_code == 201 and created.json()["status"] == "ready_to_build", created.text
    import_id = created.json()["id"]
    queued = env.client.post(env.url(f"/{import_id}/build"), headers=env.headers)
    assert queued.status_code == 202
    assert queued.json()["draft"]["status"] == "building"  # what Studio holds right after Build
    jobs = env.session.query(GenerationJob).filter(GenerationJob.business_id == env.business.id).all()
    assert len(jobs) == 1 and jobs[0].status is GenerationJobStatus.QUEUED

    _scope(monkeypatch)  # the runbook: close scoped access as soon as the job exists
    assert _capability(env, env.business.id)["mode"] == "read_only"
    assert _call(env.client, env.business.id, "build", env.headers, uuid.UUID(import_id)).status_code == 403
    building = env.client.get(env.url(f"/{import_id}"), headers=env.headers)
    assert building.status_code == 200 and building.json()["stage"] in ("queued", "building")

    # The already-created job still runs and is accepted (the worker protocol is independent of the gate).
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    assert claim.status_code == 200, claim.text
    job = env.session.get(GenerationJob, uuid.UUID(claim.json()["request"]["job_id"]))
    assert job is not None and job.id == jobs[0].id
    assert _submit(env, job, claim.json()["job_token"], built.result).status_code == 204

    ready = env.client.get(env.url(f"/{import_id}"), headers=env.headers)
    assert ready.status_code == 200
    body = ready.json()
    assert (body["status"], body["stage"]) == ("preview_ready", "preview_ready")
    draft = body["draft"]
    assert draft["status"] == "ready" and draft["artifact_sha256"] and draft["approved_artifact_sha256"] is None
    listed = env.client.get(env.url(), headers=env.headers).json()
    assert [(i["id"], i["stage"]) for i in listed] == [(import_id, "preview_ready")]

    preview = env.client.post(_draft_url(env, draft["id"], "preview"), headers=env.headers)
    assert preview.status_code == 200, preview.text
    assert artifact_sha256(env.preview.deployed[-1]) == draft["artifact_sha256"]  # exactly that artifact
    final = env.client.get(env.url(f"/{import_id}"), headers=env.headers).json()
    assert final["draft"]["status"] == "ready" and final["draft"]["approved_artifact_sha256"] is None
    assert env.publisher.artifacts == []  # nothing published
    assert env.session.query(GenerationJob).count() == 1  # no retry, no second job
