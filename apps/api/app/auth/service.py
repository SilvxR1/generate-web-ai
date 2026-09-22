"""Login/logout/session-resolution business logic (A2) — the ONE place a
password is checked or a session is created, revoked, or validated. No
FastAPI/HTTP concepts here (no cookies, no request/response objects); see
app.routers.auth for the HTTP boundary and app.dependencies for how a
resolved session becomes an authorized request.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.repositories.tenant_access import TenantAccessRepository
from app.repositories.user import UserRepository
from app.repositories.user_session import UserSessionRepository
from app.security.passwords import hash_password, verify_password
from app.security.session_tokens import generate_token, hash_token


class InvalidCredentialsError(Exception):
    """Wrong email, wrong password, or an account with no password set —
    deliberately ONE error/message for all three (see login_with_password's
    own docstring): telling them apart would let a caller enumerate which
    emails have an account."""


@dataclass(frozen=True)
class AuthenticatedSession:
    """What a successful login (or a resolved existing session) hands back
    to the HTTP layer — enough to set the cookie and build the response
    body, nothing that shouldn't leave this module (no password, no
    password hash)."""

    user: User
    raw_token: str
    csrf_token: str
    expires_at: datetime
    # Each grant, not just the Tenant — a route/response that needs the
    # per-tenant role (e.g. Studio's tenant selector, GET /auth/me) reads
    # `.role` off the grant; `.tenant` gives the Tenant row itself.
    tenant_access: list[TenantAccess]


def login_with_password(
    session: Session, *, email: str, password: str, ttl_seconds: int
) -> AuthenticatedSession:
    """Raises InvalidCredentialsError for: an unknown email, a correct
    email with the wrong password, and an account that has no
    hashed_password set at all (e.g. a User row that predates a password
    ever being set) — all three render as the exact same externally-safe
    failure, so a caller can never learn from the response alone whether a
    given email has an account. A real Argon2 verify always runs, even
    against a fixed decoy hash when the email is unknown, so the two cases
    also take roughly the same time — a response-timing side channel can't
    be used for the same enumeration either.
    """
    user = UserRepository(session).get_by_email(email)
    hashed = user.hashed_password if user is not None and user.hashed_password is not None else _decoy_hash()
    password_ok = verify_password(password, hashed)
    if user is None or user.hashed_password is None or not password_ok:
        raise InvalidCredentialsError("Invalid email or password.")
    return _create_session(session, user, ttl_seconds=ttl_seconds)


def resolve_session(session: Session, *, raw_token: str) -> AuthenticatedSession | None:
    """None for a missing, expired, revoked, or unknown token — the caller
    (app.dependencies.get_current_user) is responsible for turning that
    into a 401; this function makes no HTTP decisions."""
    user_session = UserSessionRepository(session).get_valid_by_token_hash(hash_token(raw_token))
    if user_session is None:
        return None
    user = UserRepository(session).get(user_session.user_id)
    if user is None:  # pragma: no cover — FK CASCADE makes this unreachable in practice; defensive only
        return None
    tenant_access = TenantAccessRepository(session).list_for_user(user.id)
    return AuthenticatedSession(
        user=user,
        raw_token=raw_token,
        csrf_token=user_session.csrf_token,
        expires_at=user_session.expires_at,
        tenant_access=tenant_access,
    )


def logout(session: Session, *, raw_token: str) -> None:
    """Idempotent — logging out an already-logged-out or unknown token is
    a no-op, never an error."""
    UserSessionRepository(session).revoke_by_token_hash(hash_token(raw_token))


def _create_session(session: Session, user: User, *, ttl_seconds: int) -> AuthenticatedSession:
    raw_token = generate_token()
    csrf_token = generate_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    UserSessionRepository(session).add(
        UserSession(user_id=user.id, token_hash=hash_token(raw_token), csrf_token=csrf_token, expires_at=expires_at)
    )
    tenant_access = TenantAccessRepository(session).list_for_user(user.id)
    return AuthenticatedSession(
        user=user, raw_token=raw_token, csrf_token=csrf_token, expires_at=expires_at, tenant_access=tenant_access
    )


_decoy_hash_cache: str | None = None


def _decoy_hash() -> str:
    """A real, validly-encoded Argon2 hash of a value nobody will ever
    type — computed once (lazily, not at import time, so importing this
    module never pays Argon2's cost) and reused, since its only purpose is
    to give an unknown-email login attempt a real hash to verify against
    (see login_with_password). Not a secret: its whole purpose is to be a
    fixed, public decoy, and it hashes no real credential."""
    global _decoy_hash_cache
    if _decoy_hash_cache is None:
        _decoy_hash_cache = hash_password("gwa-auth-decoy-hash-never-a-real-password-1f6c9a2e")
    return _decoy_hash_cache
