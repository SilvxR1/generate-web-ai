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
    # C2.1: when True the generated contact form shows a required consent
    # checkbox and POST /public/businesses/{id}/leads refuses a submission
    # without `consent: true` (422 consent_required). Opt-in (default
    # False) so a site already live without the checkbox keeps working:
    # enable it only after republishing a site whose form renders it.
    consent_required: bool = False
    # P1: how many days a lead is kept after its last activity in GWA (the
    # later of its last update and its newest note) before the retention
    # job (app.leads.retention) deletes it. None = never deleted
    # automatically. Enforcement only: the wording visitors read is the
    # owner's own legal_profile.data_retention, never derived from this.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
