import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import IntegrationProvider, IntegrationStatus

if TYPE_CHECKING:
    from app.db.models.business import Business
    from app.db.models.credential import Credential


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A Business's connection to one external provider. No real OAuth
    flow or provider call exists yet (out of scope for this phase) — this
    is the record a future integrations layer will attach to."""

    __tablename__ = "integrations"

    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(str_enum(IntegrationProvider, 20), nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        str_enum(IntegrationStatus, 20), nullable=False, default=IntegrationStatus.PENDING
    )
    scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="integrations")
    credential: Mapped["Credential | None"] = relationship(
        back_populates="integration", uselist=False, cascade="all, delete-orphan"
    )
