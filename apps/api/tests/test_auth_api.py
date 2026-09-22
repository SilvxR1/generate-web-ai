"""POST /auth/login, POST /auth/logout, GET /auth/me (A2) — the session
lifecycle itself: correct/incorrect credentials, unknown-email/no-password
enumeration safety, session expiry/revocation, logout invalidation, login
rate limiting, cookie flags, and CSRF enforcement on mutating authenticated
requests. Cross-tenant TenantAccess authorization (which tenant a valid
session may act as) is covered separately in
test_a2_tenant_authorization_matrix.py — this file is about the session
itself, not what it's authorized to do."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.dependencies import get_current_tenant_id, get_rate_limiter, get_session
from app.domain.enums import UserRole
from app.main import app
from app.security.passwords import hash_password
from app.security.rate_limit import InMemoryRateLimiter
from app.security.session_tokens import generate_token, hash_token

EMAIL = "owner@acme.studio"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _use_real_tenant_authentication():
    """This suite tests the real session/CSRF boundary itself — pop
    conftest's suite-wide get_current_tenant_id bypass (see its own
    docstring) so requests here go through the actual dependency chain
    instead of the pre-A2-equivalent trust-the-header shortcut every
    other (business-logic-focused) test file relies on."""
    app.dependency_overrides.pop(get_current_tenant_id, None)
    yield


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    # One shared instance across every request THIS test makes (the
    # lambda must not construct a fresh — and therefore always-empty —
    # limiter per call, or a count could never accumulate; see
    # test_rate_limit.py's own client fixture for the same precedent).
    # Still fresh per TEST: this module calls /auth/login many times
    # across many tests, all as the TestClient's fixed "testclient" host,
    # so sharing the process-wide app.dependencies._rate_limiter singleton
    # across tests would make later tests fail from earlier ones' login
    # attempts, not their own behavior.
    test_limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: test_limiter
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _create_user(session: Session, *, email: str = EMAIL, password: str | None = PASSWORD) -> User:
    user = User(email=email, hashed_password=hash_password(password) if password is not None else None)
    session.add(user)
    session.flush()
    return user


def _grant_access(session: Session, *, user: User, tenant: Tenant, role: UserRole = UserRole.OWNER) -> TenantAccess:
    access = TenantAccess(user_id=user.id, tenant_id=tenant.id, role=role)
    session.add(access)
    session.flush()
    return access


# ---------------------------------------------------------------------------
# Login: correct/incorrect credentials, enumeration safety
# ---------------------------------------------------------------------------


def test_login_succeeds_with_correct_credentials(client: TestClient, session: Session, tenant: Tenant):
    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)

    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["email"] == EMAIL
    assert isinstance(body["csrf_token"], str) and body["csrf_token"]
    assert body["tenants"] == [{"id": str(tenant.id), "name": tenant.name, "role": "owner"}]
    assert "gwa_session" in response.cookies


def test_login_fails_with_wrong_password(client: TestClient, session: Session):
    _create_user(session)

    response = client.post("/auth/login", json={"email": EMAIL, "password": "not the password"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert "gwa_session" not in response.cookies


def test_login_fails_with_unknown_email_same_error_as_wrong_password(client: TestClient, session: Session):
    _create_user(session)

    unknown = client.post("/auth/login", json={"email": "nobody@acme.studio", "password": PASSWORD})
    wrong_password = client.post("/auth/login", json={"email": EMAIL, "password": "nope"})

    # Deliberately identical status/body for "no such account" and "wrong
    # password" — see login_with_password's own docstring for why telling
    # them apart would let a caller enumerate which emails have accounts.
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_login_fails_for_user_with_no_password_set(client: TestClient, session: Session):
    _create_user(session, password=None)

    response = client.post("/auth/login", json={"email": EMAIL, "password": "anything"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_rejects_malformed_email(client: TestClient):
    response = client.post("/auth/login", json={"email": "not-an-email", "password": PASSWORD})

    assert response.status_code == 422


def test_password_and_hash_never_appear_in_login_response(client: TestClient, session: Session, tenant: Tenant):
    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant)

    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert PASSWORD not in response.text
    assert user.hashed_password not in response.text
    assert "password" not in response.json()


# ---------------------------------------------------------------------------
# GET /auth/me — session restoration
# ---------------------------------------------------------------------------


def test_me_without_cookie_is_401(client: TestClient):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_valid_session_returns_user_and_authorized_tenants(
    client: TestClient, session: Session, tenant: Tenant, other_tenant: Tenant
):
    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)
    _grant_access(session, user=user, tenant=other_tenant, role=UserRole.OPERATOR)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == EMAIL
    assert {(t["id"], t["role"]) for t in body["tenants"]} == {
        (str(tenant.id), "owner"),
        (str(other_tenant.id), "operator"),
    }


def test_me_with_garbage_cookie_is_401(client: TestClient):
    client.cookies.set("gwa_session", "not-a-real-token")

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_expired_session_is_401(client: TestClient, session: Session):
    user = _create_user(session)
    raw_token = generate_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token=generate_token(),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    session.flush()
    client.cookies.set("gwa_session", raw_token)

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_with_revoked_session_is_401(client: TestClient, session: Session):
    user = _create_user(session)
    raw_token = generate_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token=generate_token(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            revoked_at=datetime.now(UTC),
        )
    )
    session.flush()
    client.cookies.set("gwa_session", raw_token)

    response = client.get("/auth/me")

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_invalidates_the_session(client: TestClient, session: Session):
    _create_user(session)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert client.get("/auth/me").status_code == 200

    logout_response = client.post("/auth/logout")

    assert logout_response.status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_cookie_is_idempotent(client: TestClient):
    response = client.post("/auth/logout")

    assert response.status_code == 204


def test_logout_with_an_already_invalid_cookie_is_idempotent(client: TestClient):
    client.cookies.set("gwa_session", "garbage")

    response = client.post("/auth/logout")

    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Session/security properties
# ---------------------------------------------------------------------------


def test_no_raw_session_token_is_persisted(client: TestClient, session: Session):
    _create_user(session)
    login_response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    raw_token = login_response.cookies["gwa_session"]

    stored = session.query(UserSession).one()

    assert stored.token_hash != raw_token
    assert stored.token_hash == hash_token(raw_token)


def test_session_cookie_is_httponly_and_not_secure_in_dev(client: TestClient, session: Session):
    _create_user(session)

    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    set_cookie = response.headers.get("set-cookie", "")
    assert "gwa_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    # app.config.settings.environment defaults to "development" for the
    # whole test process (never overridden to "production") — see
    # app.auth.cookies' own docstring for why dev is Secure=False,
    # SameSite=Lax (same-site over http://localhost) and production is
    # Secure=True, SameSite=None (genuinely cross-site Studio/API origins).
    assert "secure" not in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_login_is_rate_limited(client: TestClient, session: Session):
    _create_user(session)
    from app.config import settings

    limit = settings.auth_login_rate_limit_per_minute
    for _ in range(limit):
        response = client.post("/auth/login", json={"email": EMAIL, "password": "wrong"})
        assert response.status_code == 401

    limited = client.post("/auth/login", json={"email": EMAIL, "password": "wrong"})

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_mutating_authenticated_request_without_csrf_token_is_rejected(
    client: TestClient, session: Session, tenant: Tenant
):
    from app.domain.enums import BusinessStatus, BusinessVertical

    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    payload = {
        "name": "Reformas Valencia",
        "slug": "reformas-valencia-csrf",
        "vertical": BusinessVertical.HOME_RENOVATION.value,
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": BusinessStatus.DRAFT.value,
    }
    response = client.post("/businesses", json=payload, headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_csrf_token"


def test_mutating_authenticated_request_with_correct_csrf_token_succeeds(
    client: TestClient, session: Session, tenant: Tenant
):
    from app.domain.enums import BusinessStatus, BusinessVertical

    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)
    login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    csrf_token = login.json()["csrf_token"]

    payload = {
        "name": "Reformas Valencia",
        "slug": "reformas-valencia-csrf-ok",
        "vertical": BusinessVertical.HOME_RENOVATION.value,
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": BusinessStatus.DRAFT.value,
    }
    response = client.post(
        "/businesses",
        json=payload,
        headers={"X-Tenant-Id": str(tenant.id), "X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 201


def test_safe_method_authenticated_request_needs_no_csrf_token(
    client: TestClient, session: Session, tenant: Tenant
):
    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    response = client.get("/businesses", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200


def test_mutating_request_with_wrong_csrf_token_is_rejected(client: TestClient, session: Session, tenant: Tenant):
    from app.domain.enums import BusinessStatus, BusinessVertical

    user = _create_user(session)
    _grant_access(session, user=user, tenant=tenant, role=UserRole.OWNER)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    payload = {
        "name": "Reformas Valencia",
        "slug": "reformas-valencia-csrf-wrong",
        "vertical": BusinessVertical.HOME_RENOVATION.value,
        "raw_description": "Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        "status": BusinessStatus.DRAFT.value,
    }
    response = client.post(
        "/businesses",
        json=payload,
        headers={"X-Tenant-Id": str(tenant.id), "X-CSRF-Token": "some-other-token"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_csrf_token"
