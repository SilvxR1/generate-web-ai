from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WebsiteVersionSummary(BaseModel):
    """Provider-neutral, read-only summary of one WebsiteVersion
    (app.db.models.website_version.WebsiteVersion) — what GET
    .../website/versions returns. Never the full `site_config` snapshot
    (Studio has no use for the raw payload; the point of this list is
    "when was this published, is it the one currently live, can I roll
    back to it" — not a config diff viewer)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    published_at: datetime
    deploy_url: str
    is_current: bool
