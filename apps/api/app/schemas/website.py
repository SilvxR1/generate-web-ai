import uuid
from datetime import datetime
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict

from app.domain.enums import DeployTarget, WebsiteStatus


class WebsiteBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deploy_target: DeployTarget = DeployTarget.CLOUDFLARE
    deploy_url: AnyHttpUrl | None = None
    status: WebsiteStatus = WebsiteStatus.DRAFT
    # Opaque WebsiteConfig snapshot for this phase — see Website model's
    # docstring. Deep validation against the real WebsiteConfig shape
    # arrives with the AI/website-generation phase, not here.
    config: dict[str, Any] | None = None
    template_id: uuid.UUID | None = None


class WebsiteCreate(WebsiteBase):
    tenant_id: uuid.UUID
    business_id: uuid.UUID


class WebsiteRead(WebsiteBase):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    business_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
