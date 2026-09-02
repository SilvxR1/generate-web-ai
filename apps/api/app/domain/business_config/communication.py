"""CommunicationConfig — which channels the business uses for outbound
communication (its own team's notifications, and customer-facing ones).
Distinct from BusinessProfile.contact (how customers reach the
business): this is about which channels the business itself uses to
notify people. No credentials here, ever — see the module-level rule
repeated in every sub-config that touches a provider name."""

from pydantic import BaseModel, ConfigDict, Field


class NotificationPreferences(BaseModel):
    """Channel toggles only. Never: smtp_password, slack_token, api_key,
    or any other credential — those belong to Credential
    (app.db.models.credential), a different bounded context."""

    model_config = ConfigDict(extra="forbid")

    email: bool = False
    whatsapp: bool = False
    slack: bool = False


class CommunicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_enabled: bool = True
    phone_enabled: bool = True
    whatsapp_enabled: bool = False
    internal_notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)
    customer_notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)
