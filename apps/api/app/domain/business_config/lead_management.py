"""LeadManagementConfig — declarative description of how the business
wants to receive and handle leads. Configuration only: no webhook
wiring, no CRM API calls, no credentials (those live on the existing
Integration/Credential entities once a real connection is made)."""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import IntegrationProvider, LeadSource


class LeadManagementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    sources: list[LeadSource] = Field(default_factory=lambda: [LeadSource.WEBSITE_FORM])
    required_fields: list[str] = Field(default_factory=lambda: ["name", "email"])
    # Which kind of destination leads should route to — reuses
    # IntegrationProvider (app.domain.enums) rather than inventing a
    # second vocabulary for "hubspot"/"google_sheets"/etc. Preference
    # only, same boundary as IntegrationPreferences: no credentials, no
    # actual connection state here.
    destination: IntegrationProvider | None = None
    acknowledgement: bool = True
    # Coarse intent flag only — the delay/schedule detail lives in
    # AutomationConfig.follow_up, which is the richer definition of the
    # same capability (see automation.py's docstring).
    follow_up: bool = False
