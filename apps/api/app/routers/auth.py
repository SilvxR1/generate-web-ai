"""POST /auth/login, POST /auth/logout, GET /auth/me (A2) — the ONLY
routes in this API that establish or end a session. Every other
tenant-scoped route continues to depend on
app.dependencies.get_current_tenant_id exactly as before; this router is
just where that session comes from.

Deliberately does NOT implement: public signup, password reset, email
verification, invitations, or MFA — all explicitly deferred (see
docs/a2-authentication-authorization.md). A User row (and its
TenantAccess grants) is created only by a reviewed, manual operator
action, never by a route in this file.
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.auth.cookies import clear_session_cookie, set_session_cookie
from app.auth.service import AuthenticatedSession, InvalidCredentialsError, login_with_password, logout
from app.config import settings
from app.dependencies import get_current_session, get_session, rate_limit_dependency
from app.errors import AppError
from app.schemas.auth import AuthenticatedTenant, CurrentUserResponse, LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _tenants(current: AuthenticatedSession) -> list[AuthenticatedTenant]:
    return [
        AuthenticatedTenant(id=access.tenant_id, name=access.tenant.name, role=access.role)
        for access in current.tenant_access
    ]


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    session: Session = Depends(get_session),
    _rate_limit: None = Depends(
        rate_limit_dependency(key_prefix="auth_login", limit_attr="auth_login_rate_limit_per_minute")
    ),
) -> LoginResponse:
    try:
        authenticated = login_with_password(
            session, email=payload.email, password=payload.password, ttl_seconds=settings.session_ttl_seconds
        )
    except InvalidCredentialsError as exc:
        # Never "unknown email" vs "wrong password" — see
        # login_with_password's own docstring for why both, plus a
        # passwordless account, all render identically here.
        raise AppError("Invalid email or password.", code="invalid_credentials", status_code=401) from exc

    set_session_cookie(response, raw_token=authenticated.raw_token, max_age_seconds=settings.session_ttl_seconds)
    return LoginResponse(
        user_id=authenticated.user.id,
        email=authenticated.user.email,
        csrf_token=authenticated.csrf_token,
        tenants=_tenants(authenticated),
    )


@router.post("/logout", status_code=204)
def logout_route(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> None:
    """Idempotent and never fails: logging out with no cookie, or one that
    is already invalid/expired, still clears the cookie client-side and
    returns 204 — a client should never need to distinguish "you weren't
    logged in" from "you're logged out now" to complete a logout action.
    Deliberately does NOT depend on get_current_session (which would 401
    a caller who's already logged out, or apply a CSRF check to an action
    whose entire purpose is ending the one thing CSRF is protecting)."""
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        logout(session, raw_token=raw_token)
    clear_session_cookie(response)


@router.get("/me", response_model=CurrentUserResponse)
def me(current: AuthenticatedSession = Depends(get_current_session)) -> CurrentUserResponse:
    """Session restoration on page load, and the ONLY source Studio's
    tenant selector may ever read its options from — never a
    client-supplied list, never localStorage."""
    return CurrentUserResponse(
        user_id=current.user.id,
        email=current.user.email,
        csrf_token=current.csrf_token,
        tenants=_tenants(current),
    )
