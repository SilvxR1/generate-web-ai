"""A2's cross-tenant authorization matrix: User A (access only to Tenant A)
and User B (access only to Tenant B), each with a real logged-in session,
against Business A (Tenant A) and Business B (Tenant B) — across every
category the design called out (business, assets, leads, reviews,
analytics, creative directions, website drafts, domains, website versions/
rollback, business deletion).

Every "cross-tenant" case here presents a REAL, valid session for a REAL
user — the thing under test is specifically whether get_current_tenant_id
(app.dependencies) ever lets that session act as a tenant it has no
TenantAccess grant for, not whether tenant-scoped repository filtering
itself works (that's the pre-existing, extensively-tested behavior in
test_business_api_isolation.py and friends — this file assumes it still
holds and adds the new layer on top).

Deliberately uses the REAL authentication dependency chain, not conftest's
suite-wide get_current_tenant_id bypass — see
_use_real_tenant_authentication below."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.business_asset import BusinessAsset
from app.db.models.business_review import BusinessReview
from app.db.models.creative_direction import CreativeDirection
from app.db.models.custom_domain import CustomDomain
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.db.models.website_draft import WebsiteDraft
from app.db.models.website_version import WebsiteVersion
from app.dependencies import get_current_tenant_id, get_rate_limiter, get_session
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    BusinessStatus,
    BusinessVertical,
    DomainStatus,
    ReviewSource,
    UserRole,
)
from app.main import app
from app.security.passwords import hash_password
from app.security.rate_limit import InMemoryRateLimiter

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _use_real_tenant_authentication():
    """See test_auth_api.py's identical fixture — this matrix is
    specifically about the TenantAccess authorization boundary, so it
    must not run under conftest's default bypass."""
    app.dependency_overrides.pop(get_current_tenant_id, None)
    yield


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.fixture()
def business_a(session: Session, tenant: Tenant) -> Business:
    b = Business(
        tenant_id=tenant.id,
        name="Reformas Valencia",
        slug="reformas-valencia",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        status=BusinessStatus.DRAFT,
    )
    session.add(b)
    session.flush()
    return b


@pytest.fixture()
def business_b(session: Session, other_tenant: Tenant) -> Business:
    b = Business(
        tenant_id=other_tenant.id,
        name="Cositas y Puntos",
        slug="cositas-y-puntos",
        vertical=BusinessVertical.OTHER,
        raw_description="Tienda de manualidades y papeleria creativa en Madrid.",
        status=BusinessStatus.DRAFT,
    )
    session.add(b)
    session.flush()
    return b


@pytest.fixture()
def user_a(session: Session, tenant: Tenant) -> User:
    user = User(email="usera@acme.studio", hashed_password=hash_password(PASSWORD))
    session.add(user)
    session.flush()
    session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OWNER))
    session.flush()
    return user


@pytest.fixture()
def user_b(session: Session, other_tenant: Tenant) -> User:
    user = User(email="userb@acme.studio", hashed_password=hash_password(PASSWORD))
    session.add(user)
    session.flush()
    session.add(TenantAccess(user_id=user.id, tenant_id=other_tenant.id, role=UserRole.OWNER))
    session.flush()
    return user


def _login(client: TestClient, *, user: User) -> str:
    response = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _seed_business_b_content(session: Session, business_b: Business) -> dict:
    asset = BusinessAsset(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        kind=AssetKind.IMAGE,
        category=AssetCategory.OTHER,
        origin=AssetOrigin.UPLOADED,
        storage_url="https://cdn.example.com/cositas/product.png",
    )
    review = BusinessReview(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        source=ReviewSource.MANUAL,
        body="Excelente atencion y productos preciosos.",
    )
    direction = CreativeDirection(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        concept={},
        visual_language={},
        experience={},
        content_strategy={},
        constraints={},
    )
    draft = WebsiteDraft(tenant_id=business_b.tenant_id, business_id=business_b.id, site_config={})
    domain = CustomDomain(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        domain="cositasypuntos.example.com",
        status=DomainStatus.PENDING_VERIFICATION,
    )
    version = WebsiteVersion(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        site_config={},
        deploy_url="https://cositas.pages.dev",
        published_at=datetime.now(UTC),
    )
    lead = Lead(
        tenant_id=business_b.tenant_id,
        business_id=business_b.id,
        source="website_form",
        created_at=datetime.now(UTC),
    )
    session.add_all([asset, review, direction, draft, domain, version, lead])
    session.flush()
    return {
        "asset": asset,
        "review": review,
        "direction": direction,
        "draft": draft,
        "domain": domain,
        "version": version,
        "lead": lead,
    }


# ---------------------------------------------------------------------------
# Each category: User A (Tenant A only) reaching for Tenant B's business
# must be denied exactly like an unknown tenant — never reach the data.
# User B (the real owner) making the identical call must succeed.
# ---------------------------------------------------------------------------


def test_business_detail_cross_tenant_denied(client, session, user_a, user_b, business_b, tenant, other_tenant):
    _login(client, user=user_a)
    denied = client.get(f"/businesses/{business_b.id}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(f"/businesses/{business_b.id}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert allowed.status_code == 200
    assert allowed.json()["id"] == str(business_b.id)


def test_business_list_cross_tenant_denied(client, session, user_a, other_tenant):
    _login(client, user=user_a)
    response = client.get("/businesses", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_assets_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    seeded = _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(f"/businesses/{business_b.id}/assets", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(f"/businesses/{business_b.id}/assets", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert allowed.status_code == 200
    assert [a["id"] for a in allowed.json()] == [str(seeded["asset"].id)]


def test_leads_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(f"/businesses/{business_b.id}/leads", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(f"/businesses/{business_b.id}/leads", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1


def test_reviews_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    seeded = _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(f"/businesses/{business_b.id}/reviews", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(f"/businesses/{business_b.id}/reviews", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert allowed.status_code == 200
    assert [r["id"] for r in allowed.json()] == [str(seeded["review"].id)]


def test_analytics_metrics_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    _login(client, user=user_a)
    denied = client.get(
        f"/businesses/{business_b.id}/metrics", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(
        f"/businesses/{business_b.id}/metrics", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert allowed.status_code == 200


def test_creative_directions_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    seeded = _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(
        f"/businesses/{business_b.id}/creative-directions", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(
        f"/businesses/{business_b.id}/creative-directions", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert allowed.status_code == 200
    assert [d["id"] for d in allowed.json()] == [str(seeded["direction"].id)]


def test_website_drafts_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    seeded = _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(
        f"/businesses/{business_b.id}/website-drafts", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(
        f"/businesses/{business_b.id}/website-drafts", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert allowed.status_code == 200
    assert [d["id"] for d in allowed.json()] == [str(seeded["draft"].id)]


def test_domain_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied = client.get(
        f"/businesses/{business_b.id}/website/domain", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed = client.get(
        f"/businesses/{business_b.id}/website/domain", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert allowed.status_code == 200
    assert allowed.json()["domain"] == "cositasypuntos.example.com"


def test_website_versions_and_rollback_cross_tenant_denied(
    client, session, user_a, user_b, business_b, other_tenant
):
    seeded = _seed_business_b_content(session, business_b)

    _login(client, user=user_a)
    denied_list = client.get(
        f"/businesses/{business_b.id}/website/versions", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert denied_list.status_code == 404
    assert denied_list.json()["error"]["code"] == "unknown_tenant"

    csrf_token = _login(client, user=user_a)  # re-login as A to also get a CSRF token
    denied_rollback = client.post(
        f"/businesses/{business_b.id}/website/versions/{seeded['version'].id}/rollback",
        headers={"X-Tenant-Id": str(other_tenant.id), "X-CSRF-Token": csrf_token},
    )
    assert denied_rollback.status_code == 404
    assert denied_rollback.json()["error"]["code"] == "unknown_tenant"

    client.cookies.clear()
    _login(client, user=user_b)
    allowed_list = client.get(
        f"/businesses/{business_b.id}/website/versions", headers={"X-Tenant-Id": str(other_tenant.id)}
    )
    assert allowed_list.status_code == 200
    assert len(allowed_list.json()) == 1


def test_business_deletion_cross_tenant_denied(client, session, user_a, user_b, business_b, other_tenant):
    csrf_token = _login(client, user=user_a)
    denied = client.delete(
        f"/businesses/{business_b.id}",
        headers={"X-Tenant-Id": str(other_tenant.id), "X-CSRF-Token": csrf_token},
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "unknown_tenant"
    # Never deleted — the real owner can still see it.
    client.cookies.clear()
    _login(client, user=user_b)
    still_there = client.get(f"/businesses/{business_b.id}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert still_there.status_code == 200


def test_business_deletion_by_real_owner_succeeds(client, session, user_b, business_b, other_tenant):
    csrf_token = _login(client, user=user_b)
    response = client.delete(
        f"/businesses/{business_b.id}",
        headers={"X-Tenant-Id": str(other_tenant.id), "X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 204

    gone = client.get(f"/businesses/{business_b.id}", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "business_not_found"


def test_user_a_can_fully_act_on_their_own_tenant(client, session, user_a, business_a, tenant):
    """The matrix's positive control on User A's own side too — denial
    above must be specific to Tenant B, not a general breakage of
    get_current_tenant_id for User A."""
    _login(client, user=user_a)
    response = client.get(f"/businesses/{business_a.id}", headers={"X-Tenant-Id": str(tenant.id)})
    assert response.status_code == 200
    assert response.json()["id"] == str(business_a.id)


def test_knowing_a_real_tenant_uuid_grants_nothing_without_a_grant(client, session, user_a, tenant, other_tenant):
    """The core A2 property, stated directly: other_tenant.id is a real,
    valid Tenant row — User A simply has no TenantAccess for it, and
    that alone is enough to deny, with the exact same error a bogus
    tenant id would get (see test_unknown_tenant_uuid_denied_identically
    below) — an authenticated caller can never tell "real tenant, no
    access" apart from "no such tenant"."""
    _login(client, user=user_a)
    response = client.get("/businesses", headers={"X-Tenant-Id": str(other_tenant.id)})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_unknown_tenant_uuid_denied_identically(client, session, user_a):
    import uuid

    _login(client, user=user_a)
    response = client.get("/businesses", headers={"X-Tenant-Id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant"


def test_no_session_with_tenant_header_only_is_401_not_authorized(client, session, tenant):
    """The other half of A2's headline requirement: a caller presenting
    ONLY a (real) X-Tenant-Id, no session cookie at all, must be
    rejected outright — never silently authenticated by the header
    alone (settings.legacy_tenant_header_auth_enabled defaults False for
    exactly this reason)."""
    response = client.get("/businesses", headers={"X-Tenant-Id": str(tenant.id)})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
