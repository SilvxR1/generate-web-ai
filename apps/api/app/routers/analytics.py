"""GET /businesses/{id}/metrics (P1.8) — window-scoped business
acquisition metrics for Studio's Business Metrics panel. Read-only;
POST /public/businesses/{id}/events (app.routers.public) is the only
write path for analytics data."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.analytics_events.metrics import compute_business_metrics
from app.dependencies import get_current_tenant_id, get_session
from app.errors import AppError
from app.repositories.business import BusinessRepository
from app.schemas.analytics import BusinessMetricsRead

router = APIRouter(prefix="/businesses/{business_id}", tags=["analytics"])

_WINDOW_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/metrics", response_model=BusinessMetricsRead)
def get_business_metrics(
    business_id: UUID,
    window: Literal["7d", "30d", "90d"] = Query(default="30d"),
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> BusinessMetricsRead:
    if BusinessRepository(session).get(tenant_id, business_id) is None:
        raise AppError("Business not found.", code="business_not_found", status_code=status.HTTP_404_NOT_FOUND)

    metrics = compute_business_metrics(
        session, tenant_id=tenant_id, business_id=business_id, window_days=_WINDOW_DAYS[window]
    )
    return BusinessMetricsRead(
        window_days=metrics.window_days,
        website_visits=metrics.website_visits,
        whatsapp_clicks=metrics.whatsapp_clicks,
        phone_clicks=metrics.phone_clicks,
        email_clicks=metrics.email_clicks,
        form_leads=metrics.form_leads,
        lead_conversion_rate=metrics.lead_conversion_rate,
    )
