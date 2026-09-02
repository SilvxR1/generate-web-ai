from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.template import Template
    from app.db.models.user import User


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The isolation root. Every other business entity carries a
    tenant_id back to one of these — see TenantScopedMixin."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    businesses: Mapped[list["Business"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    templates: Mapped[list["Template"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
