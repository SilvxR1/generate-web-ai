from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select

from app.db.models.lead import Lead
from app.domain.enums import LeadStatus
from app.repositories.base import TenantScopedRepository


class LeadRepository(TenantScopedRepository[Lead]):
    model = Lead

    def list_for_business(
        self,
        tenant_id: UUID,
        business_id: UUID,
        *,
        status: LeadStatus | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> list[Lead]:
        """Most-recent-first, scoped to both tenant and business — the
        Studio leads list reads this directly, so ordering lives here
        rather than being left to the caller to remember. `status`/
        `source`/`search` (P1.3) are all optional and additive: omitting
        every one of them is exactly the old "every lead for this
        business" behavior. `search` matches name/email/phone/subject/
        message case-insensitively (a plain substring match — no full-text
        search engine, this isn't a CRM); it never matches against
        `lead_metadata`, which may carry non-visitor-facing provenance
        data (see Lead.lead_metadata's own docstring)."""
        stmt = select(Lead).where(Lead.tenant_id == tenant_id, Lead.business_id == business_id)
        if status is not None:
            stmt = stmt.where(Lead.status == status)
        if source is not None:
            stmt = stmt.where(Lead.source == source)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Lead.name.ilike(pattern),
                    Lead.email.ilike(pattern),
                    Lead.phone.ilike(pattern),
                    Lead.subject.ilike(pattern),
                    Lead.message.ilike(pattern),
                )
            )
        stmt = stmt.order_by(Lead.created_at.desc())
        return list(self.session.scalars(stmt).all())

    def count_in_window(self, tenant_id: UUID, business_id: UUID, *, since: datetime) -> int:
        """Real leads captured since `since` — the authoritative,
        always-known "form leads" figure for app.analytics_events.metrics
        (P1.8): unlike consent-gated analytics events, every real Lead is
        always captured regardless of visitor consent, so 0 here is a
        genuine known count, never "no data yet"."""
        stmt = select(func.count()).where(
            Lead.tenant_id == tenant_id, Lead.business_id == business_id, Lead.created_at >= since
        )
        return int(self.session.scalar(stmt) or 0)

    def get_for_business(self, tenant_id: UUID, business_id: UUID, lead_id: UUID) -> Lead | None:
        """Like the base class's `get`, but also requires `business_id`
        to match — the base version alone would let a caller update a
        lead that belongs to a *different* business owned by the same
        tenant, as long as they knew its id. Used by PATCH
        /businesses/{id}/leads/{id}/status (app.routers.businesses) so
        that endpoint can't cross a business boundary within one tenant,
        not just a tenant boundary."""
        stmt = select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id, Lead.business_id == business_id)
        return self.session.scalars(stmt).first()
