from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.tenant_access import TenantAccess
    from app.db.models.user_session import UserSession


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can log into Studio (A2) — deliberately NOT
    tenant-scoped: which tenant(s) a User may act as is an authorization
    fact recorded on TenantAccess, never on User itself. This is the
    architectural correction A2 makes over this table's original (never
    populated, never read by any router/service) shape, which carried its
    own `tenant_id` and a `uq_users_tenant_email` constraint — the exact
    "User -> exactly one Tenant" model A2 explicitly replaces. See
    app.db.models.tenant_access.TenantAccess for the actual access grant.

    `email` is therefore now the identity a login looks up BEFORE any
    tenant is known, so it must be globally unique, not per-tenant.
    `hashed_password` is an Argon2id encoded hash (app.security.passwords)
    — the raw password is never stored or logged anywhere. Nullable only
    because this table's own history shows a User can exist before this
    column existed; every User created after A2 always sets it at creation
    time via app.auth.service.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant_accesses: Mapped[list["TenantAccess"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
