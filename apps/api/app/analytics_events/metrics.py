"""Business acquisition metrics (P1.8): window-scoped counts, built from
two different sources on purpose — AnalyticsEvent (consent-gated,
client-side, may have real coverage gaps) for visits/CTA clicks, and the
authoritative Lead table (always captured, consent-independent) for real
form leads. "No data yet" (None) vs. a real 0 is decided per source:
AnalyticsEventRepository.has_any_for_business gates every analytics-
derived field uniformly (P1.8's "If data is unavailable... show 'No data
yet' not zero unless zero is actually known"); Lead-derived fields are
never None — a real Lead is always known.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.enums import AnalyticsEventType
from app.repositories.analytics_event import AnalyticsEventRepository
from app.repositories.lead import LeadRepository


@dataclass(frozen=True)
class BusinessMetrics:
    window_days: int
    website_visits: int | None
    whatsapp_clicks: int | None
    phone_clicks: int | None
    email_clicks: int | None
    form_leads: int
    lead_conversion_rate: float | None


def compute_business_metrics(
    session: Session, *, tenant_id: UUID, business_id: UUID, window_days: int
) -> BusinessMetrics:
    since = datetime.now(UTC) - timedelta(days=window_days)
    analytics_repo = AnalyticsEventRepository(session)
    has_analytics = analytics_repo.has_any_for_business(tenant_id, business_id)

    def _count(event_type: AnalyticsEventType) -> int | None:
        if not has_analytics:
            return None
        return analytics_repo.count_in_window(tenant_id, business_id, event_type=event_type, since=since)

    website_visits = _count(AnalyticsEventType.PAGE_VIEW)
    whatsapp_clicks = _count(AnalyticsEventType.WHATSAPP_CLICK)
    phone_clicks = _count(AnalyticsEventType.PHONE_CLICK)
    email_clicks = _count(AnalyticsEventType.EMAIL_CLICK)
    form_leads = LeadRepository(session).count_in_window(tenant_id, business_id, since=since)

    conversion_rate = None
    if website_visits is not None and website_visits > 0:
        conversion_rate = form_leads / website_visits

    return BusinessMetrics(
        window_days=window_days,
        website_visits=website_visits,
        whatsapp_clicks=whatsapp_clicks,
        phone_clicks=phone_clicks,
        email_clicks=email_clicks,
        form_leads=form_leads,
        lead_conversion_rate=conversion_rate,
    )
