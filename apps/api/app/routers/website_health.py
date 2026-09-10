"""GET/POST /businesses/{id}/website-health (P1.4-P1.5): the latest
Website Health snapshot, and the "Check now" action that (re)computes it.
Deliberately not bound to any scheduler — app.monitoring's own docstring
explains why; this router is simply *a* caller of
app.monitoring.service.run_website_health_check, the same one a future
n8n workflow or cron job would also call.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.models.website_health import WebsiteHealthCheck
from app.dependencies import get_current_tenant_id, get_session, rate_limit_dependency
from app.errors import AppError
from app.monitoring.service import run_website_health_check
from app.repositories.business import BusinessRepository
from app.repositories.website_health import WebsiteHealthCheckRepository
from app.schemas.website_health import WebsiteHealthRead

router = APIRouter(prefix="/businesses/{business_id}/website-health", tags=["website-health"])


def _ensure_business_exists(session: Session, tenant_id: UUID, business_id: UUID) -> None:
    if BusinessRepository(session).get(tenant_id, business_id) is None:
        raise AppError("Business not found.", code="business_not_found", status_code=status.HTTP_404_NOT_FOUND)


@router.get("", response_model=WebsiteHealthRead | None)
def get_website_health(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> WebsiteHealthCheck | None:
    """The latest snapshot, or null (200) if this business has never had
    a check run — same "nothing to show yet" convention as GET
    .../website. Never triggers a new check itself (that's the POST
    below) — a plain read is always instant."""
    _ensure_business_exists(session, tenant_id, business_id)
    return WebsiteHealthCheckRepository(session).get_for_business(tenant_id, business_id)


@router.post("/check", response_model=WebsiteHealthRead)
def check_website_health_now(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    _rate_limit: None = Depends(
        rate_limit_dependency(key_prefix="website_health_check", limit_attr="website_health_rate_limit_per_minute")
    ),
) -> WebsiteHealthCheck:
    """Runs a real check right now and returns the fresh snapshot —
    Studio's "Check now" button. Rate-limited (real outbound HTTP/DNS/TLS
    calls, not a free read) the same way the public lead endpoint is."""
    _ensure_business_exists(session, tenant_id, business_id)
    return run_website_health_check(session, tenant_id=tenant_id, business_id=business_id)
