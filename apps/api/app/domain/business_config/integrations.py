"""IntegrationPreferences — which provider the business wants for each
integration category. Preferences only: no credentials, no OAuth tokens,
no provider client objects (Section 10's explicit boundary). Actual
connection state lives on the existing Integration/Credential entities
(app.db.models) — a different bounded context this config never touches.
"""

from pydantic import BaseModel, ConfigDict

from app.domain.enums import IntegrationProvider


class IntegrationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crm: IntegrationProvider | None = None
    email: IntegrationProvider | None = None
    internal_notifications: IntegrationProvider | None = None
    spreadsheets: IntegrationProvider | None = None
