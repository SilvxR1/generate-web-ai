import uuid
from datetime import datetime
from typing import Protocol

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin:
    """Every business entity carries an unambiguous, denormalized link to
    its Tenant — not just via its parent (Business.tenant_id), but on the
    row itself. This is deliberate defense-in-depth for tenant isolation
    (Section 13 of the master context): a repository can filter by
    `tenant_id` directly on any table without trusting a join chain to be
    correct, and a bug in one relationship can't silently leak another
    tenant's rows through a different path."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


class TenantScopedModel(Protocol):
    """Structural typing anchor only — never instantiated or mapped.
    Every concrete tenant-scoped model already has `id`/`tenant_id` via
    the two mixins above (through actual inheritance, not this Protocol);
    this lets `TenantScopedRepository[ModelT: TenantScopedModel]` state
    that requirement in a way mypy checks structurally, instead of
    `ModelT` being bound to plain `Base` (which knows about neither
    column) or to a concrete class every model would need to also
    inherit from."""

    id: Mapped[uuid.UUID]
    tenant_id: Mapped[uuid.UUID]
