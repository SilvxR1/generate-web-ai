from pydantic import BaseModel, ConfigDict


class OperationalProviderAvailability(BaseModel):
    """One row of GET /businesses/{id}/operational-providers (P1.12) —
    the notification/automation counterpart to
    CreativeProviderAvailability (app.schemas.creative) and
    ReviewProviderAvailability (app.schemas.creative): honest, real-
    settings-backed availability, never a hardcoded placeholder.
    `provider` is a plain string (not a shared enum — email has two
    interchangeable providers, Resend and SMTP, that no other part of
    this codebase needs to distinguish between at the type level)."""

    model_config = ConfigDict(extra="forbid")

    category: str
    provider: str
    available: bool
    unavailable_reason: str | None = None
