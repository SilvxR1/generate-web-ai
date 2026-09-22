import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import UserRole

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.user import User


class TenantAccess(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The ONLY fact that authorizes a User to act as a Tenant (A2) —
    knowing a Tenant's UUID grants nothing; a matching row here must exist.
    Deliberately many-to-many (a User may hold access to several tenants,
    e.g. our own operator account across every managed customer; a Tenant
    may eventually have several Users once real customer logins exist) —
    see this table's own migration for why this replaced an earlier
    "User belongs to exactly one Tenant" shape.

    `role` is recorded per grant (not on User) precisely so a future
    owner/member distinction can be layered onto existing rows without any
    schema change or re-authentication — this PR does not yet enforce any
    behavior difference between roles; it only records the fact so that
    distinction can be added later. Every grant is created explicitly by an
    operator action (see the A2 cutover procedure); nothing in this
    codebase creates one implicitly.
    """

    __tablename__ = "tenant_access"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_tenant_access_user_tenant"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, 20), nullable=False, default=UserRole.OPERATOR)

    user: Mapped["User"] = relationship(back_populates="tenant_accesses")
    tenant: Mapped["Tenant"] = relationship(back_populates="tenant_accesses")
