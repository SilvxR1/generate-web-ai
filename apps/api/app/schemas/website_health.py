import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.domain.enums import HealthStatus


class WebsiteHealthRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    checked_at: datetime
    checked_url: str | None
    overall_status: HealthStatus
    http_status: HealthStatus
    http_status_code: int | None
    http_latency_ms: float | None
    dns_status: HealthStatus
    tls_status: HealthStatus
    tls_expires_at: datetime | None
    tls_days_remaining: int | None
    deployment_status: HealthStatus
    deployment_last_deployed_at: datetime | None
    form_status: HealthStatus
    error_summary: str | None
