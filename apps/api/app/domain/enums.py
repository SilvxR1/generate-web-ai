"""Domain vocabulary shared by the database models (app.db.models) and the
Pydantic schemas (app.schemas). Defined once here so the two layers can
never drift into representing the same concept two different ways.
"""

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"


class BusinessVertical(StrEnum):
    """Extensible on purpose (Section 4 of the master context: don't
    hardcode the product to the reformas vertical). New verticals are added
    here as they're validated with real clients; OTHER is the escape hatch
    until then."""

    HOME_RENOVATION = "home_renovation"
    REAL_ESTATE = "real_estate"
    CLINIC = "clinic"
    AGENCY = "agency"
    B2B_SERVICES = "b2b_services"
    RESTAURANT = "restaurant"
    ECOMMERCE = "ecommerce"
    HOTEL = "hotel"
    OTHER = "other"


class BusinessStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"


class DeployTarget(StrEnum):
    CLOUDFLARE = "cloudflare"


class WebsiteStatus(StrEnum):
    DRAFT = "draft"
    BUILDING = "building"
    LIVE = "live"
    FAILED = "failed"


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class WorkflowVersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"


class ConfigOrigin(StrEnum):
    """Who produced a given WorkflowVersion's definition — the AI proposal
    or a human edit. Mirrors the master context's Section 5 requirement
    that every generated artifact's provenance stay traceable."""

    AI = "ai"
    HUMAN = "human"


class IntegrationProvider(StrEnum):
    """MVP scope only (Section 9's stated priority order). Extend as later
    providers are added — Outlook, Teams, Drive, Notion, Salesforce,
    WhatsApp, Telegram."""

    WEBHOOK = "webhook"
    GMAIL = "gmail"
    GOOGLE_SHEETS = "google_sheets"
    SLACK = "slack"
    HUBSPOT = "hubspot"


class IntegrationStatus(StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ExecutionType(StrEnum):
    WORKFLOW_RUN = "workflow_run"
    WEBSITE_BUILD = "website_build"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TemplateKind(StrEnum):
    WEBSITE_BLOCK = "website_block"
    WORKFLOW_PATTERN = "workflow_pattern"


class Weekday(StrEnum):
    """Used by BusinessProfile's business_hours (app.domain.business_config)
    — a controlled vocabulary in place of packages/site-config's
    LocalBusinessOpeningHours.dayOfWeek, which is free-text on the
    TypeScript side (schema.org's DayOfWeek values) because that layer is
    trusted, hand-authored content. This layer isn't."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class LeadSource(StrEnum):
    """Where a lead can come from — Section 8's stated initial set."""

    WEBSITE_FORM = "website_form"
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    MANUAL = "manual"
    OTHER = "other"


class LeadStatus(StrEnum):
    """A lead's basic follow-up state. Deliberately just these four —
    not a CRM pipeline: no custom stages, no per-tenant configurability.
    NEW is always where a lead starts (see Lead.status's default);
    CONTACTED/WON/LOST are set by a human via PATCH
    /businesses/{id}/leads/{id}/status, never by the system itself."""

    NEW = "new"
    CONTACTED = "contacted"
    WON = "won"
    LOST = "lost"
