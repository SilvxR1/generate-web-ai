"""BusinessConfig — the structured source of truth for a business.

    BusinessConfig
    ├── business_profile   (required — everything else has defaults)
    ├── brand
    ├── website             intent/preferences, not generated content — see website.py
    ├── lead_management
    ├── communications
    ├── integrations        preferences, never credentials — see integrations.py
    └── automation          intent, not an executable workflow — see automation.py

Pure domain data: no FastAPI, no SQLAlchemy, no n8n, no AI-provider
SDKs, no React. app.schemas.business (the API layer) composes this in as
a field; app.db.models.business persists it as an opaque JSON blob
(Business.config) with zero knowledge of this class. See each
sub-module's docstring for what it deliberately does and doesn't cover,
and the architecture-design phase's decision log for the target
BusinessConfig -> {WebsiteConfig, WorkflowConfig} split this is the
first half of.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.brand import BrandConfig
from app.domain.business_config.business_profile import BusinessProfile
from app.domain.business_config.communication import CommunicationConfig
from app.domain.business_config.integrations import IntegrationPreferences
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.business_config.website import WebsiteConfig

CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION = 1


class BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION
    business_profile: BusinessProfile
    brand: BrandConfig | None = None
    website: WebsiteConfig = Field(default_factory=WebsiteConfig)
    lead_management: LeadManagementConfig = Field(default_factory=LeadManagementConfig)
    communications: CommunicationConfig = Field(default_factory=CommunicationConfig)
    integrations: IntegrationPreferences = Field(default_factory=IntegrationPreferences)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)

    @field_validator("schema_version")
    @classmethod
    def _known_schema_version(cls, value: int) -> int:
        if value != CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version {value}; this API only understands "
                f"{CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION} (no config migration framework built yet — "
                "see Section 12's deliberate scope limit)."
            )
        return value
