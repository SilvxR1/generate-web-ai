import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import WebsiteDraftStatus
from app.schemas.site_config import SiteConfigPayload


class WebsiteDraftCreateRequest(BaseModel):
    """Body for POST /businesses/{id}/website-drafts. `site_config` is the
    exact SiteConfig Studio already computed (generateSiteConfig(),
    the same object its own live preview and POST .../website/publish
    already use) — this backend never recomputes it, the same "never
    drift" guarantee SiteConfigPayload's own docstring describes.
    `creative_generation_id` links this draft back to the
    CreativeGeneration that produced it, when there is one."""

    model_config = ConfigDict(extra="forbid")

    site_config: SiteConfigPayload
    creative_generation_id: uuid.UUID | None = None


class WebsiteDraftRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    creative_generation_id: uuid.UUID | None
    site_config: dict
    status: WebsiteDraftStatus
    build_error: str | None
    validation_issues: list[str] | None
    approved_at: datetime | None
    published_at: datetime | None
    published_website_id: uuid.UUID | None
    created_at: datetime
