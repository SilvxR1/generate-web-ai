import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import DomainStatus

# A conservative hostname syntax check only — at least one dot (so a bare
# "localhost"-shaped value can't be submitted), letters/digits/hyphens
# per label, no leading/trailing hyphen. This app never verifies
# ownership or registration itself (Cloudflare's own DNS validation is
# what actually proves the human controls this domain) — this regex
# exists purely to reject obviously-malformed input before it reaches
# Cloudflare's API.
_DOMAIN_PATTERN = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


class CustomDomainCreateRequest(BaseModel):
    """Body for POST .../website/domain (app.routers.businesses). This
    app never purchases or registers a domain — `domain` must already be
    owned by the business; Studio's own copy on the attach form says so
    explicitly (P0's "DO NOT purchase domains automatically" constraint)."""

    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=253)

    @field_validator("domain")
    @classmethod
    def _normalize_and_validate(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not _DOMAIN_PATTERN.match(normalized):
            raise ValueError("Enter a valid domain name you already own (e.g. example.com).")
        return normalized


class CustomDomainState(BaseModel):
    """Provider-neutral, persisted snapshot of a business's custom-domain
    attachment (app.db.models.custom_domain.CustomDomain) — what every
    domain endpoint returns. `cname_target` and `provider_status` are
    safe to show a human as-is; neither is ever a credential."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    status: DomainStatus
    provider_status: str | None
    cname_target: str | None
    error_message: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
