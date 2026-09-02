from typing import TYPE_CHECKING

from sqlalchemy import JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import BusinessVertical, TemplateKind

if TYPE_CHECKING:
    from app.db.models.tenant import Tenant
    from app.db.models.website import Website
    from app.db.models.workflow_version import WorkflowVersion


class Template(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """A reusable pattern promoted from repeated custom work (Section 15:
    custom -> config -> template -> product feature). Belongs to a Tenant
    (the agency's growing library), not to a single Business — a Business
    reaches a Template only indirectly, through the Website/WorkflowVersion
    that was generated from it (see `template_id` on those models)."""

    __tablename__ = "templates"

    kind: Mapped[TemplateKind] = mapped_column(str_enum(TemplateKind, 20), nullable=False)
    vertical: Mapped[BusinessVertical | None] = mapped_column(str_enum(BusinessVertical, 30), nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    tenant: Mapped["Tenant"] = relationship(back_populates="templates")
    websites: Mapped[list["Website"]] = relationship(back_populates="template")
    workflow_versions: Mapped[list["WorkflowVersion"]] = relationship(back_populates="template")
