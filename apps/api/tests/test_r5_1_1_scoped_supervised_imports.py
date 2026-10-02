# ruff: noqa: F811 — pytest fixtures imported from tests/test_r5_source_imports.py
"""R5.1.1 — scoped supervised-import access for an explicitly allowlisted
canary business while the global feature stays OFF.

The allowlist is additive: it only decides whether the existing supervised
import capability may be used for one exact business. Authentication,
tenant authorization, review, blockers, plan identity, the worker protocol,
artifact approval and publish authority are untouched — proved here with
the REAL session/tenant authorization chain where it matters.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.creative import source_imports as imports
from app.creative.source_adapter.fixtures import lumen_physio_business_config
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.dependencies import get_current_tenant_id, get_current_user
from app.domain.enums import BusinessStatus, BusinessVertical, UserRole
from app.main import app
from app.routers.source_imports import require_supervised_import_access, require_supervised_import_read, router
from app.security.passwords import hash_password
from tests.test_r5_source_imports import (  # noqa: F401 — shared fixtures
    Env,
    _variant_zip,
    env,
)

SEVEN = ("upload", "list", "get", "diagnostics", "decisions", "reinspect", "build", "discard")  # + R5.2 discard
# R5.1.3: the write gate guards the four mutating routes; the three reads also
# serve a business's EXISTING imports once write access is closed.
WRITES = ("upload", "decisions", "reinspect", "build", "discard")
READS = ("list", "get", "diagnostics")


def _scope(monkeypatch: pytest.MonkeyPatch, *, global_on: bool = False, allow: str = "") -> None:
    monkeypatch.setattr(settings, "supervised_source_imports_enabled", global_on)
    monkeypatch.setattr(settings, "supervised_source_imports_business_ids", allow)


def _business(env: Env, tenant_id: uuid.UUID, slug: str) -> Business:
    business = Business(
        tenant_id=tenant_id,
        name=f"Canary {slug}",
        slug=slug,
        vertical=BusinessVertical.CLINIC,
        raw_description="Fictional R5.1.1 business.",
        status=BusinessStatus.DRAFT,
        config=lumen_physio_business_config().model_dump(mode="json"),
    )
    env.session.add(business)
    env.session.flush()
    return business


def _call(client: TestClient, business_id: uuid.UUID, route: str, headers: dict, import_id: uuid.UUID | None = None):
    base = f"/businesses/{business_id}/source-imports"
    item = f"{base}/{import_id or uuid.uuid4()}"
    if route == "upload":
        return client.post(base, headers=headers, files={"file": ("x.zip", b"PK\x03\x04-not-a-zip", "application/zip")})
    if route == "list":
        return client.get(base, headers=headers)
    if route == "get":
        return client.get(item, headers=headers)
    if route == "diagnostics":
        return client.get(f"{item}/diagnostics", headers=headers)
    if route == "decisions":
        body = {"finding_id": "x", "decision": "approved", "rationale": "canary test"}
        return client.post(f"{item}/decisions", headers=headers, json=body)
    if route == "reinspect":
        return client.post(f"{item}/reinspect", headers=headers)
    if route == "discard":
        return client.post(f"{item}/discard", headers=headers, json={"reason": "canary test"})
    return client.post(f"{item}/build", headers=headers)


def _capability(env: Env, business_id: uuid.UUID) -> dict:
    response = env.client.get(f"/businesses/{business_id}/source-imports/capability", headers=env.headers)
    assert response.status_code == 200, response.text
    return response.json()


# --- Configuration semantics ------------------------------------------------------------------


def test_allowlist_parsing_is_exact_canonical_and_fails_closed():
    a, b = uuid.uuid4(), uuid.uuid4()
    parse = imports.parse_business_allowlist
    assert parse("") == frozenset() and parse("   \n ") == frozenset()
    assert parse(f"{a}") == {a}
    assert parse(f"  {a} ,{b}\n{a}\t, ,{a}") == {a, b}  # whitespace/commas; duplicates harmless
    assert parse(str(a).upper()) == {a}  # canonical form, any case
    for malformed in (
        "*",
        "all",
        "ALL",
        f"{a},*",
        f"{a},all",
        str(a)[:8],  # a prefix
        str(a).replace("-", ""),  # hex without hyphens
        "{" + str(a) + "}",
        f"urn:uuid:{a}",
        f"{a};{b}",
        "not-a-uuid",
        f"{a} garbage",
    ):
        assert parse(malformed) == frozenset(), malformed  # one bad entry disables EVERY business


def test_access_resolution(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    _scope(monkeypatch)
    assert imports.supervised_import_access(a) == "disabled"
    _scope(monkeypatch, allow=f"{a}")
    assert (imports.supervised_import_access(a), imports.supervised_import_access(b)) == ("scoped", "disabled")
    _scope(monkeypatch, global_on=True)
    assert imports.supervised_import_access(b) == "global"
    _scope(monkeypatch, global_on=True, allow=f"{a}")
    assert (imports.supervised_import_access(a), imports.supervised_import_access(b)) == ("global", "global")
    _scope(monkeypatch, allow=f"{a},*")
    assert imports.supervised_import_access(a) == "disabled"


# --- One write gate on every mutating route; one read gate on every read (R5.1.3) ------------------


def test_every_mutating_route_uses_the_write_gate_and_every_read_the_read_gate():
    def deps(route) -> set:
        found, stack = set(), list(route.dependant.dependencies)
        while stack:
            dep = stack.pop()
            found.add(dep.call)
            stack.extend(dep.dependencies)
        return found

    gates = {
        (method, r.path): (
            require_supervised_import_access in deps(r),  # type: ignore[attr-defined]
            require_supervised_import_read in deps(r),  # type: ignore[attr-defined]
        )
        for r in router.routes
        for method in r.methods  # type: ignore[attr-defined]
    }
    base = "/businesses/{business_id}/source-imports"
    assert gates.pop(("GET", f"{base}/capability")) == (False, False)
    writes = {
        ("POST", base),
        *(("POST", f"{base}/{{import_id}}/{a}") for a in ("decisions", "reinspect", "build", "discard")),
    }
    reads = {("GET", base), ("GET", f"{base}/{{import_id}}"), ("GET", f"{base}/{{import_id}}/diagnostics")}
    assert set(gates) == writes | reads, gates
    assert all(gates[key] == (True, False) for key in writes), gates  # a mutation never takes the read gate
    assert all(gates[key] == (False, True) for key in reads), gates


def test_global_off_and_empty_allowlist_refuses_all_seven(env: Env, monkeypatch):
    _scope(monkeypatch)
    for route in SEVEN:
        response = _call(env.client, env.business.id, route, env.headers)
        assert response.status_code == 403 and response.json()["error"]["code"] == "feature_not_available", route
    capability = _capability(env, env.business.id)
    assert capability["access"] == "disabled" and capability["enabled"] is False
    assert capability["mode"] == "disabled" and capability["read_enabled"] is False


def test_an_allowlisted_business_gets_the_full_supervised_workflow_with_the_feature_off(
    env: Env, monkeypatch, tmp_path
):
    _scope(monkeypatch, allow=f"{env.business.id}")
    created = env.upload(_variant_zip(tmp_path, "scoped"))
    assert created.status_code == 201, created.text
    import_id = uuid.UUID(created.json()["id"])
    assert created.json()["status"] == "ready_to_build"
    for route in ("list", "get", "diagnostics", "reinspect"):
        assert _call(env.client, env.business.id, route, env.headers, import_id).status_code == 200, route
    decided = _call(env.client, env.business.id, "decisions", env.headers, import_id)
    assert decided.status_code not in (401, 403, 404), decided.text  # reached the review logic, past the gate
    assert _call(env.client, env.business.id, "build", env.headers, import_id).status_code == 202
    # The existing worker protocol picks the job up exactly as before.
    claim = env.client.post(
        "/internal/generation-worker/claim", headers=env.worker(), json={"isolation": "supervised-process"}
    )
    assert claim.status_code == 200 and claim.json()["request"]["business_id"] == str(env.business.id)
    capability = _capability(env, env.business.id)
    assert capability["access"] == "scoped" and capability["enabled"] is True


def test_allowlisting_a_does_not_open_b(env: Env, monkeypatch):
    other = _business(env, env.tenant.id, "canary-b")
    _scope(monkeypatch, allow=f"{env.business.id}")
    for route in SEVEN:
        assert _call(env.client, other.id, route, env.headers).status_code == 403, route
    assert _capability(env, other.id)["access"] == "disabled"


def test_an_import_of_one_business_is_unreachable_through_another_businesss_path(env: Env, monkeypatch, tmp_path):
    other = _business(env, env.tenant.id, "canary-b")
    _scope(monkeypatch, allow=f"{env.business.id},{other.id}")
    import_id = uuid.UUID(env.upload(_variant_zip(tmp_path, "a")).json()["id"])
    for route in ("get", "diagnostics", "decisions", "reinspect", "build"):
        assert _call(env.client, other.id, route, env.headers, import_id).status_code == 404, route
    _scope(monkeypatch, allow=f"{other.id}")  # only B allowlisted now: A's import is read-only (R5.1.3)
    assert _call(env.client, env.business.id, "get", env.headers, import_id).status_code == 200
    for route in WRITES:
        assert _call(env.client, env.business.id, route, env.headers, import_id).status_code == 403, route
    for route in ("get", "diagnostics"):  # B's write access still never reaches A's import
        assert _call(env.client, other.id, route, env.headers, import_id).status_code == 404, route


@pytest.mark.parametrize("with_allowlist", [False, True])
def test_global_on_keeps_the_existing_behaviour(env: Env, monkeypatch, tmp_path, with_allowlist):
    other = _business(env, env.tenant.id, "canary-b")
    _scope(monkeypatch, global_on=True, allow=str(other.id) if with_allowlist else "")
    assert env.upload(_variant_zip(tmp_path, "global")).status_code == 201
    assert _capability(env, env.business.id)["access"] == "global"
    assert _call(env.client, other.id, "list", env.headers).status_code == 200


def test_malformed_or_wildcard_configuration_fails_closed(env: Env, monkeypatch):
    for raw in ("*", "all", f"{env.business.id},*", str(env.business.id)[:8], "not-a-uuid"):
        _scope(monkeypatch, allow=raw)
        assert _call(env.client, env.business.id, "list", env.headers).status_code == 403, raw
        assert _capability(env, env.business.id)["access"] == "disabled"


def test_duplicates_are_harmless(env: Env, monkeypatch):
    _scope(monkeypatch, allow=f"{env.business.id}, {env.business.id}\n{env.business.id}")
    assert _call(env.client, env.business.id, "list", env.headers).status_code == 200


def test_capability_never_reveals_the_allowlist(env: Env, monkeypatch):
    other = _business(env, env.tenant.id, "canary-b")
    neighbour = uuid.uuid4()
    _scope(monkeypatch, allow=f"{env.business.id},{other.id},{neighbour}")
    for business_id in (env.business.id, other.id):
        response = env.client.get(f"/businesses/{business_id}/source-imports/capability", headers=env.headers)
        assert response.json()["access"] == "scoped"
        others = {str(i) for i in (env.business.id, other.id, neighbour)} - {str(business_id)}
        assert not any(i in response.text for i in others)
        assert "business_ids" not in response.text


def test_removing_or_changing_the_allowlist_closes_subsequent_actions(env: Env, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    import_id = uuid.UUID(env.upload(_variant_zip(tmp_path, "removed")).json()["id"])
    _scope(monkeypatch)
    for route in WRITES:
        assert _call(env.client, env.business.id, route, env.headers, import_id).status_code == 403, route
    for route in READS:  # R5.1.3: the existing import stays readable
        assert _call(env.client, env.business.id, route, env.headers, import_id).status_code == 200, route
    _scope(monkeypatch, allow=f"{uuid.uuid4()}")  # changed to another business
    assert _call(env.client, env.business.id, "build", env.headers, import_id).status_code == 403


# --- Real authentication and tenant authorization ------------------------------------------------


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


@pytest.fixture()
def two_tenants(env: Env):
    """Tenant A (the env business) with its operator, and tenant B with an
    operator who has NO access to tenant A. Real auth: overrides removed."""
    password = "r5-1-1-" + uuid.uuid4().hex
    env.user.hashed_password = hash_password(password)
    tenant_b = Tenant(name="Other tenant")
    env.session.add(tenant_b)
    env.session.flush()
    outsider = User(email="outsider@r511.example", hashed_password=hash_password(password))
    env.session.add(outsider)
    env.session.flush()
    env.session.add(TenantAccess(user_id=outsider.id, tenant_id=tenant_b.id, role=UserRole.OPERATOR))
    env.session.flush()
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_current_tenant_id, None)
    return {"password": password, "tenant_b": tenant_b, "outsider": outsider}


def test_without_a_session_nothing_is_reachable_even_when_allowlisted(env: Env, two_tenants, monkeypatch):
    _scope(monkeypatch, allow=f"{env.business.id}")
    client = TestClient(app)
    for route in SEVEN:
        assert _call(client, env.business.id, route, {"X-Tenant-Id": str(env.tenant.id)}).status_code == 401, route


def test_an_operator_of_another_tenant_cannot_use_an_allowlisted_business(env: Env, two_tenants, monkeypatch, tmp_path):
    _scope(monkeypatch, allow=f"{env.business.id}")
    owner = TestClient(app)
    csrf = _login(owner, env.user.email, two_tenants["password"])
    created = owner.post(
        f"/businesses/{env.business.id}/source-imports",
        headers={"X-Tenant-Id": str(env.tenant.id), "X-CSRF-Token": csrf},
        files={"file": ("a.zip", _variant_zip(tmp_path, "real"), "application/zip")},
    )
    assert created.status_code == 201, created.text  # the authorized operator of A: allowed
    import_id = uuid.UUID(created.json()["id"])

    outsider = TestClient(app)
    csrf_b = _login(outsider, two_tenants["outsider"].email, two_tenants["password"])
    claiming_a = {"X-Tenant-Id": str(env.tenant.id), "X-CSRF-Token": csrf_b}  # a tenant they have no access to
    own_tenant = {"X-Tenant-Id": str(two_tenants["tenant_b"].id), "X-CSRF-Token": csrf_b}
    for route in SEVEN:
        assert _call(outsider, env.business.id, route, claiming_a, import_id).status_code == 404, route
        assert _call(outsider, env.business.id, route, own_tenant, import_id).status_code == 404, route
    capability = outsider.get(f"/businesses/{env.business.id}/source-imports/capability", headers=own_tenant)
    assert capability.status_code == 404
    # The existing draft/artifact routes are untouched: the outsider reaches none of them either.
    for suffix in ("approve", "publish", "preview"):
        url = f"/businesses/{env.business.id}/website-drafts/{uuid.uuid4()}/{suffix}"
        assert outsider.post(url, headers=own_tenant).status_code == 404, suffix
