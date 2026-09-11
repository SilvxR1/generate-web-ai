from typing import TYPE_CHECKING

from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.columns import str_enum
from app.db.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import BusinessStatus, BusinessVertical

if TYPE_CHECKING:
    from app.db.models.business_asset import BusinessAsset
    from app.db.models.business_review import BusinessReview
    from app.db.models.creative_direction import CreativeDirection
    from app.db.models.creative_generation import CreativeGeneration
    from app.db.models.custom_domain import CustomDomain
    from app.db.models.execution import Execution
    from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
    from app.db.models.integration import Integration
    from app.db.models.internal_notification import InternalNotification
    from app.db.models.lead import Lead
    from app.db.models.tenant import Tenant
    from app.db.models.website import Website
    from app.db.models.website_draft import WebsiteDraft
    from app.db.models.workflow import Workflow


class Business(UUIDPrimaryKeyMixin, TimestampMixin, TenantScopedMixin, Base):
    """The central entity: everything else (Website, Workflow,
    Integration, Execution, BusinessAsset, BusinessReview,
    CreativeGeneration) hangs off a Business.

    `name`/`vertical`/`slug` are relational columns even though the same
    facts also live inside `config.business_profile` (name/industry/slug)
    once a BusinessConfig is attached. This is a deliberate, documented
    materialized-projection pattern — not two independent sources of
    truth by accident — kept for cheap listing/lookup/uniqueness (`slug`
    needs a real index; querying inside a JSON blob for it does not scale
    the same way) without needing every caller to parse `config` first.
    Nothing currently enforces the two stay in sync; see the
    business-configuration-system phase's technical-debt notes.
    """

    __tablename__ = "businesses"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_businesses_tenant_slug"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    vertical: Mapped[BusinessVertical] = mapped_column(str_enum(BusinessVertical, 30), nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[BusinessStatus] = mapped_column(
        str_enum(BusinessStatus, 20), nullable=False, default=BusinessStatus.DRAFT
    )
    # The BusinessConfig payload (app.domain.business_config.BusinessConfig),
    # serialized as plain JSON. This model deliberately does not import
    # that Pydantic class — persistence stays ignorant of the domain
    # shape it stores (Section 2's boundary); (de)serialization happens
    # at the service/API layer. `default=1` mirrors
    # CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION by value, not by import.
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    tenant: Mapped["Tenant"] = relationship(back_populates="businesses")
    website: Mapped["Website | None"] = relationship(
        back_populates="business", uselist=False, cascade="all, delete-orphan"
    )
    custom_domain: Mapped["CustomDomain | None"] = relationship(
        back_populates="business", uselist=False, cascade="all, delete-orphan"
    )
    workflows: Mapped[list["Workflow"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    integrations: Mapped[list["Integration"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    executions: Mapped[list["Execution"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    leads: Mapped[list["Lead"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    internal_notifications: Mapped[list["InternalNotification"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    assets: Mapped[list["BusinessAsset"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    reviews: Mapped[list["BusinessReview"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    creative_generations: Mapped[list["CreativeGeneration"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    website_drafts: Mapped[list["WebsiteDraft"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    creative_directions: Mapped[list["CreativeDirection"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    generative_website_artifacts: Mapped[list["GenerativeWebsiteArtifact"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
