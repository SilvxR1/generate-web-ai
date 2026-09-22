import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.enums import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # A length bound only — see app.security.passwords.MAX_PASSWORD_LENGTH
    # for the exact limit this must not exceed; kept slightly generous here
    # so a too-long password fails with the service's own clear error
    # rather than a generic 422 that doesn't say why.
    password: str = Field(min_length=1, max_length=1024)


class AuthenticatedTenant(BaseModel):
    """One tenant the logged-in user is authorized for — never more than
    what TenantAccess actually grants (see app.repositories.tenant_access).
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    role: UserRole


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    email: str
    # The value the client must echo back as X-CSRF-Token on every
    # mutating request for the rest of this session — see
    # app.dependencies' CSRF check for why. Never derivable from the
    # session cookie alone (that cookie is HttpOnly and unreadable by JS).
    csrf_token: str
    tenants: list[AuthenticatedTenant]


class CurrentUserResponse(BaseModel):
    """GET /auth/me — session restoration on page load. Same shape as
    LoginResponse (Studio treats both identically) plus nothing a
    logged-out or cross-tenant caller shouldn't see."""

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    email: str
    csrf_token: str
    tenants: list[AuthenticatedTenant]
