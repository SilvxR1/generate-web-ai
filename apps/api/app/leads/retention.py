"""P1: lead deletion and retention.

One deletion path for both an operator's request (a visitor asking for
erasure) and the retention job:

- `delete_lead` removes a lead and every GWA record that repeats its
  personal data — its notes and the internal notifications about it (their
  `summary` names the visitor) — and writes one LeadDeletionEvent that keeps
  no personal data. Scoped by tenant AND business AND lead; a lead of another
  business is "not found", never deleted. Idempotent: deleting a lead that
  this business already deleted returns the earlier event.
- `expired_leads` / `purge_expired_leads` apply a business's
  `lead_management.retention_days`: a lead whose last activity in GWA (the
  later of its last update and its newest note) is older than that many days
  is deleted. Businesses without a retention period are never touched. The
  job is a dry run unless `apply=True`.

What this does NOT reach (and never claims to): copies outside GWA's
database — n8n execution history, Resend's logs, the owner's inbox and
database backups. See docs/lead-retention.md.

    python -m app.leads.retention                 # dry run, every business with a policy
    python -m app.leads.retention --apply         # delete what the dry run lists
    python -m app.leads.retention --business-id <uuid> [--apply]
"""

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.lead_deletion_event import LeadDeletionEvent
from app.db.models.lead_note import LeadNote
from app.db.models.user import User
from app.domain.business_config import BusinessConfig
from app.domain.enums import LeadDeletionReason
from app.errors import AppError
from app.repositories.lead import LeadRepository


def delete_lead(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    business_id: uuid.UUID,
    lead_id: uuid.UUID,
    reason: LeadDeletionReason,
    actor: User | None = None,
) -> tuple[LeadDeletionEvent, bool]:
    """(event, deleted_now). Raises 404 `lead_not_found` for a lead this
    business never had (or that belongs to another business or tenant)."""
    lead = LeadRepository(session).lock_for_business(tenant_id, business_id, lead_id)
    if lead is None:
        earlier = session.scalars(
            select(LeadDeletionEvent).where(
                LeadDeletionEvent.tenant_id == tenant_id,
                LeadDeletionEvent.business_id == business_id,
                LeadDeletionEvent.lead_id == lead_id,
            )
        ).first()
        if earlier is None:
            raise AppError("Lead not found.", code="lead_not_found", status_code=404)
        return earlier, False

    def scope(model):
        return model.tenant_id == tenant_id, model.business_id == business_id, model.lead_id == lead_id

    deleted_notifications = session.execute(delete(InternalNotification).where(*scope(InternalNotification)))
    notifications = getattr(deleted_notifications, "rowcount", 0)
    notes = getattr(session.execute(delete(LeadNote).where(*scope(LeadNote))), "rowcount", 0)
    event = LeadDeletionEvent(
        tenant_id=tenant_id,
        business_id=business_id,
        lead_id=lead_id,
        reason=reason,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        lead_created_at=lead.created_at,
        notes_deleted=notes or 0,
        notifications_deleted=notifications or 0,
    )
    session.add(event)
    session.delete(lead)
    session.flush()
    return event, True


def retention_days(business: Business) -> int | None:
    """The business's retention period, or None (no policy, or a config that
    doesn't validate — never guessed)."""
    if not business.config:
        return None
    try:
        return BusinessConfig.model_validate(business.config).lead_management.retention_days
    except ValidationError:
        return None


def expired_leads(session: Session, business: Business, *, now: datetime) -> list[Lead]:
    days = retention_days(business)
    if days is None:
        return []
    cutoff = now - timedelta(days=days)
    newest_note = (
        select(func.max(LeadNote.created_at)).where(LeadNote.lead_id == Lead.id).correlate(Lead).scalar_subquery()
    )
    stmt = select(Lead).where(
        Lead.tenant_id == business.tenant_id,
        Lead.business_id == business.id,
        Lead.updated_at < cutoff,
        or_(newest_note.is_(None), newest_note < cutoff),
    )
    return list(session.scalars(stmt).all())


@dataclass(frozen=True)
class RetentionRun:
    """One business's result — counts and dates only, never personal data."""

    business_id: str
    retention_days: int
    cutoff: str
    expired: int
    deleted: int


def purge_expired_leads(
    session: Session, *, now: datetime | None = None, apply: bool = False, business_id: uuid.UUID | None = None
) -> list[RetentionRun]:
    now = now or datetime.now(UTC)
    query = select(Business).order_by(Business.id)
    if business_id is not None:
        query = query.where(Business.id == business_id)
    runs: list[RetentionRun] = []
    for business in session.scalars(query).all():
        days = retention_days(business)
        if days is None:
            continue
        expired = expired_leads(session, business, now=now)
        deleted = 0
        if apply:
            for lead in expired:
                _, now_deleted = delete_lead(
                    session,
                    tenant_id=business.tenant_id,
                    business_id=business.id,
                    lead_id=lead.id,
                    reason=LeadDeletionReason.RETENTION_EXPIRED,
                )
                deleted += now_deleted
        runs.append(
            RetentionRun(
                business_id=str(business.id),
                retention_days=days,
                cutoff=(now - timedelta(days=days)).isoformat(),
                expired=len(expired),
                deleted=deleted,
            )
        )
    return runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete leads older than their business's retention period.")
    parser.add_argument("--apply", action="store_true", help="delete (default: dry run, nothing is changed)")
    parser.add_argument("--business-id", type=uuid.UUID)
    args = parser.parse_args(argv)

    from app.dependencies import engine  # the configured database; imported late so tests never touch it

    with Session(engine) as session:
        runs = purge_expired_leads(session, apply=args.apply, business_id=args.business_id)
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(json.dumps({"apply": args.apply, "businesses": [asdict(r) for r in runs]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
