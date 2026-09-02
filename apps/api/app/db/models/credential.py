import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.integration import Integration


class Credential(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """Holds only the Fernet-encrypted secret (see
    app.security.encryption.CredentialCipher) — plaintext never reaches
    this table. One Credential per Integration for the MVP."""

    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("integration_id", name="uq_credentials_integration_id"),)

    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    integration: Mapped["Integration"] = relationship(back_populates="credential")
