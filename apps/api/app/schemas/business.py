import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.business_config import SLUG_PATTERN, BusinessConfig
from app.domain.enums import BusinessStatus, BusinessVertical


class BusinessBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=100, pattern=SLUG_PATTERN.pattern)
    vertical: BusinessVertical
    # The original natural-language description the AI Business Analyzer
    # will eventually consume (Section 1's "Business Description" input).
    # Bounded so a runaway paste can't reach the LLM unbounded — the AI
    # layer itself is out of scope for this phase.
    raw_description: str = Field(min_length=10, max_length=5000)
    status: BusinessStatus = BusinessStatus.DRAFT

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class BusinessWriteRequest(BusinessBase):
    """Body for both POST /businesses and PUT /businesses/{id} (full
    replace) — no `tenant_id` field. Tenant scoping is never accepted
    from request input (Section 17): the route derives it from
    `get_current_tenant_id` and passes it separately to the service.

    `config` (BusinessConfig) is optional and independent of
    `name`/`vertical`/`slug` above — this API does not currently enforce
    that `config.business_profile.name`/`.industry`/`.slug` match the
    top-level fields when both are set. See Business's docstring
    (app.db.models.business) for why the top-level columns exist at all,
    and the business-configuration-system phase's technical-debt notes
    for this specific gap.
    """

    config: BusinessConfig | None = None


class BusinessCreate(BusinessWriteRequest):
    """Same shape as BusinessWriteRequest plus `tenant_id`, required for
    repository/service-layer callers (tests, scripts, the API's own
    service after it resolves the trusted tenant) — never constructed
    directly from raw request input."""

    tenant_id: uuid.UUID


class BusinessRead(BusinessBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    config: BusinessConfig | None
    config_schema_version: int
    created_at: datetime
    updated_at: datetime


class AutomationRecommendationResponse(BaseModel):
    """Response for GET /businesses/automation-recommendation — a
    direct, stateless mirror of
    app.domain.workflow_config.vertical_templates.AutomationTemplate's
    four fields, computed fresh from `vertical` on every request. Never
    persisted anywhere and never itself a BusinessConfig: it exists so
    Studio can show and let a user apply the recommendation into the
    normal BusinessConfig draft, not as a second, parallel source of
    configuration."""

    model_config = ConfigDict(extra="forbid")

    lead_notifications: bool
    customer_acknowledgement: bool
    follow_up_enabled: bool
    follow_up_delay_hours: int
