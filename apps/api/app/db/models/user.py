from typing import TYPE_CHECKING

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import UserRole

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant


class User(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, 20), nullable=False, default=UserRole.OPERATOR)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
