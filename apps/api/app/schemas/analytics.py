import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import AnalyticsEventType

# A crude but effective PII trip-wire on metadata *values* only (keys are
# already constrained to a short allow-list pattern below) — this
# endpoint has no legitimate reason to ever receive an email address or a
# long digit run (a phone number) in event metadata (P1.7: "Analytics
# events should not contain ... email addresses ... phone numbers").
# Rejecting outright (422) rather than silently stripping keeps a
# misbehaving client visible instead of masking the bug.
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_LONG_DIGIT_RUN_PATTERN = re.compile(r"\d{7,}")
_METADATA_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_MAX_METADATA_KEYS = 5
_MAX_METADATA_VALUE_LENGTH = 200


class AnalyticsEventCreateRequest(BaseModel):
    """Body for POST /public/businesses/{id}/events (P1.7) — the one
    anonymous analytics surface, mirroring PublicLeadCreateRequest's
    "no X-Tenant-Id, tenant derived server-side from the business row"
    shape (app.routers.public). `event_type` is a closed enum (never
    free text); `metadata` is small, key-constrained, and scanned for
    obvious PII shapes — see this module's own top-level docstring."""

    model_config = ConfigDict(extra="forbid")

    event_type: AnalyticsEventType
    # Client-supplied timestamp is never trusted for ordering/aggregation
    # (app.routers.analytics always uses server receipt time) — accepted
    # here only so a client can report it for its own debugging, and
    # deliberately unused past validation.
    occurred_at: datetime | None = None
    source_page: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, str] | None = None

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        if len(value) > _MAX_METADATA_KEYS:
            raise ValueError(f"metadata may carry at most {_MAX_METADATA_KEYS} keys.")
        for key, item in value.items():
            if not _METADATA_KEY_PATTERN.match(key):
                raise ValueError(f"metadata key {key!r} is not allowed.")
            if len(item) > _MAX_METADATA_VALUE_LENGTH:
                raise ValueError(f"metadata value for {key!r} is too long.")
            if _EMAIL_PATTERN.search(item) or _LONG_DIGIT_RUN_PATTERN.search(item):
                raise ValueError("metadata must not contain personal information such as an email or phone number.")
        return value


class AnalyticsEventCreateResponse(BaseModel):
    """Always `{"received": true}` regardless of internal outcome — same
    "never teach a bot what was rejected" shape as
    PublicLeadCreateResponse."""

    model_config = ConfigDict(extra="forbid")

    received: bool = True


class BusinessMetricsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: int
    website_visits: int | None
    whatsapp_clicks: int | None
    phone_clicks: int | None
    email_clicks: int | None
    form_leads: int
    lead_conversion_rate: float | None
