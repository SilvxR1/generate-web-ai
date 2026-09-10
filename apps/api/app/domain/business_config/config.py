"""BusinessConfig — the structured source of truth for a business.

    BusinessConfig
    ├── business_profile   (required — everything else has defaults)
    ├── brand
    ├── legal_profile       real legal-entity facts, never fabricated — see legal.py
    ├── website             intent/preferences, not generated content — see website.py
    ├── creative            strategy/level intent — see creative.py
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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.business_config.automation import AutomationConfig
from app.domain.business_config.brand import BrandConfig
from app.domain.business_config.business_profile import BusinessProfile
from app.domain.business_config.communication import CommunicationConfig
from app.domain.business_config.creative import CreativeConfig
from app.domain.business_config.integrations import IntegrationPreferences
from app.domain.business_config.lead_management import LeadManagementConfig
from app.domain.business_config.legal import LegalProfile
from app.domain.business_config.website import WebsiteConfig
from app.domain.enums import LeadSource

CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION = 1


class BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = CURRENT_BUSINESS_CONFIG_SCHEMA_VERSION
    business_profile: BusinessProfile
    brand: BrandConfig | None = None
    legal_profile: LegalProfile | None = None
    website: WebsiteConfig = Field(default_factory=WebsiteConfig)
    creative: CreativeConfig = Field(default_factory=CreativeConfig)
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

    @model_validator(mode="after")
    def _sync_lead_management_with_website_lead_capture_intent(self) -> "BusinessConfig":
        """`automation.lead_capture` is, in this codebase, always realized
        as a workflow triggered by a website form submission
        (app.domain.workflow_config.generator.generate_lead_capture_workflow
        unconditionally builds a LeadSubmittedTrigger, which
        app.automation.n8n.translator maps to LeadSource.WEBSITE_FORM) —
        so any path that produces a BusinessConfig with lead-capture
        automation enabled (the AI analyzer's proposal, a Studio-authored
        config, a script) must also represent that intent in
        lead_management, or the result is an active n8n workflow with no
        way for the generated website to ever trigger it
        (packages/website-generator's buildContactBlock only emits a
        contact form when WEBSITE_FORM is among lead_management.sources).

        This normalizes rather than rejects, since WEBSITE_FORM is a
        derivable consequence of the stated automation intent, not a
        genuine ambiguity requiring a human decision. It never drops an
        existing, legitimately-configured source (email, phone,
        whatsapp...) to make room for it, and only fills in
        required_fields when the config left it empty — an explicit,
        non-empty choice is always preserved.
        """
        if not self.automation.lead_capture:
            return self

        lead_management = self.lead_management
        needs_website_form = LeadSource.WEBSITE_FORM not in lead_management.sources
        needs_enabling = not lead_management.enabled
        needs_required_fields = not lead_management.required_fields

        if not (needs_website_form or needs_enabling or needs_required_fields):
            return self

        sources = [*lead_management.sources, LeadSource.WEBSITE_FORM] if needs_website_form else lead_management.sources
        required_fields = lead_management.required_fields or ["name", "email"]
        self.lead_management = lead_management.model_copy(
            update={"enabled": True, "sources": sources, "required_fields": required_fields}
        )
        return self
