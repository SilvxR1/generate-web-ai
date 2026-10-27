"""P1 — deleting a lead, and the per-business retention job.

Runs under the REAL authentication chain (session cookie + CSRF + TenantAccess):
deletion names the operator who did it. Checked here: what goes with a lead
(notes, internal notifications that name the visitor), what never does (other
leads, other businesses, other tenants), that the audit record keeps no
personal data, that repeating a deletion is a no-op, and that the retention
job is a dry run by default and touches only businesses with a policy.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.lead_deletion_event import LeadDeletionEvent
from app.db.models.lead_note import LeadNote
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.dependencies import get_current_tenant_id, get_rate_limiter, get_session
from app.domain.business_config import BusinessConfig
from app.domain.enums import BusinessStatus, BusinessVertical, LeadDeletionReason, UserRole
from app.leads import retention
from app.leads.retention import delete_lead, purge_expired_leads
from app.main import app
from app.security.passwords import hash_password
from app.security.rate_limit import InMemoryRateLimiter

PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
VISITOR = {"name": "Visitante Ficticia", "email": "visitante@example.com", "phone": "600000000", "message": "Hola"}


@pytest.fixture(autouse=True)
def _use_real_tenant_authentication():
    app.dependency_overrides.pop(get_current_tenant_id, None)
    yield


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _business(session: Session, tenant: Tenant, slug: str, *, retention_days: int | None = None) -> Business:
    config = {"business_profile": {"name": slug, "slug": slug, "industry": "other"}}
    if retention_days is not None:
        config["lead_management"] = {"retention_days": retention_days}
    b = Business(
        tenant_id=tenant.id,
        name=slug,
        slug=slug,
        vertical=BusinessVertical.OTHER,
        raw_description="Negocio ficticio de prueba.",
        status=BusinessStatus.DRAFT,
        config=BusinessConfig.model_validate(config).model_dump(mode="json"),
    )
    session.add(b)
    session.flush()
    return b


def _user(session: Session, tenant: Tenant, email: str) -> User:
    user = User(email=email, hashed_password=hash_password(PASSWORD))
    session.add(user)
    session.flush()
    session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
    session.flush()
    return user


def _lead(session: Session, business: Business, *, age_days: int = 0) -> Lead:
    when = NOW - timedelta(days=age_days)
    lead = Lead(
        tenant_id=business.tenant_id,
        business_id=business.id,
        source="website_form",
        created_at=when,
        updated_at=when,
        **VISITOR,
    )
    session.add(lead)
    session.flush()
    return lead


def _note(session: Session, lead: Lead, *, age_days: int = 0) -> LeadNote:
    when = NOW - timedelta(days=age_days)
    note = LeadNote(
        tenant_id=lead.tenant_id, business_id=lead.business_id, lead_id=lead.id, body="Llamada", created_at=when
    )
    session.add(note)
    session.flush()
    return note


def _notification(session: Session, lead: Lead) -> InternalNotification:
    n = InternalNotification(
        tenant_id=lead.tenant_id,
        business_id=lead.business_id,
        lead_id=lead.id,
        channel="internal",
        source="public_lead_form",
        summary=f"New lead from {lead.name}.",
    )
    session.add(n)
    session.flush()
    return n


def _login(client: TestClient, user: User) -> str:
    response = client.post("/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _delete(client: TestClient, csrf: str, tenant: Tenant, business: Business, lead_id: uuid.UUID):
    return client.delete(
        f"/businesses/{business.id}/leads/{lead_id}",
        headers={"X-Tenant-Id": str(tenant.id), "X-CSRF-Token": csrf},
    )


def _exists(session: Session, model, **where) -> bool:
    return session.scalars(select(model).filter_by(**where)).first() is not None


# --- deleting one lead ----------------------------------------------------------------------------


def test_an_operator_deletes_a_lead_with_its_notes_and_notifications(client, session, tenant):
    business = _business(session, tenant, "taller-a")
    user = _user(session, tenant, "operadora@example.com")
    lead, kept = _lead(session, business), _lead(session, business)
    _note(session, lead)
    _note(session, lead)
    _notification(session, lead)
    _notification(session, kept)

    response = _delete(client, _login(client, user), tenant, business, lead.id)

    assert response.status_code == 204 and response.content == b""
    session.expire_all()
    assert not _exists(session, Lead, id=lead.id)
    assert not _exists(session, LeadNote, lead_id=lead.id)
    assert not _exists(session, InternalNotification, lead_id=lead.id)
    assert _exists(session, Lead, id=kept.id) and _exists(session, InternalNotification, lead_id=kept.id)
    [event] = session.scalars(select(LeadDeletionEvent)).all()
    assert (event.business_id, event.lead_id, event.reason) == (
        business.id,
        lead.id,
        LeadDeletionReason.OPERATOR_REQUEST,
    )
    assert (event.actor_user_id, event.actor_email) == (user.id, user.email)
    assert (event.notes_deleted, event.notifications_deleted) == (2, 1)


def test_the_deletion_record_keeps_no_personal_data_of_the_visitor(client, session, tenant):
    business = _business(session, tenant, "taller-a")
    user = _user(session, tenant, "operadora@example.com")
    lead = _lead(session, business)
    _delete(client, _login(client, user), tenant, business, lead.id)

    row = session.scalars(select(LeadDeletionEvent)).one()
    stored = " ".join(str(getattr(row, c.key)) for c in LeadDeletionEvent.__table__.columns)
    for value in VISITOR.values():
        assert value not in stored


def test_deleting_the_same_lead_again_is_a_no_op(client, session, tenant):
    business = _business(session, tenant, "taller-a")
    user = _user(session, tenant, "operadora@example.com")
    lead = _lead(session, business)
    csrf = _login(client, user)

    assert _delete(client, csrf, tenant, business, lead.id).status_code == 204
    assert _delete(client, csrf, tenant, business, lead.id).status_code == 204
    assert len(session.scalars(select(LeadDeletionEvent)).all()) == 1


def test_an_unknown_lead_is_not_found(client, session, tenant):
    business = _business(session, tenant, "taller-a")
    user = _user(session, tenant, "operadora@example.com")
    response = _delete(client, _login(client, user), tenant, business, uuid.uuid4())
    assert response.status_code == 404 and response.json()["error"]["code"] == "lead_not_found"
    assert session.scalars(select(LeadDeletionEvent)).all() == []


def test_a_lead_of_another_business_of_the_same_tenant_is_never_deleted(client, session, tenant):
    business, other = _business(session, tenant, "taller-a"), _business(session, tenant, "taller-b")
    user = _user(session, tenant, "operadora@example.com")
    lead = _lead(session, other)

    response = _delete(client, _login(client, user), tenant, business, lead.id)

    assert response.status_code == 404
    assert _exists(session, Lead, id=lead.id)


def test_another_tenants_lead_is_never_deleted(client, session, tenant, other_tenant):
    mine = _business(session, tenant, "taller-a")
    theirs = _business(session, other_tenant, "taller-ajeno")
    user = _user(session, tenant, "operadora@example.com")
    lead = _lead(session, theirs)
    csrf = _login(client, user)

    assert _delete(client, csrf, other_tenant, theirs, lead.id).status_code == 404  # no TenantAccess
    assert _delete(client, csrf, tenant, theirs, lead.id).status_code == 404  # not this tenant's business
    assert _delete(client, csrf, tenant, mine, lead.id).status_code == 404  # not this business's lead
    assert _exists(session, Lead, id=lead.id)


def test_deletion_needs_a_session_and_the_csrf_token(client, session, tenant):
    business = _business(session, tenant, "taller-a")
    user = _user(session, tenant, "operadora@example.com")
    lead = _lead(session, business)
    url, tenant_header = f"/businesses/{business.id}/leads/{lead.id}", {"X-Tenant-Id": str(tenant.id)}

    assert client.delete(url, headers=tenant_header).status_code == 401
    _login(client, user)
    assert client.delete(url, headers=tenant_header).status_code == 403  # signed in, but no CSRF token
    assert _exists(session, Lead, id=lead.id)


# --- retention ------------------------------------------------------------------------------------


def test_the_retention_period_is_validated():
    profile = {"name": "x", "slug": "x", "industry": "other"}
    for invalid in (0, -1, 3651):
        with pytest.raises(ValidationError):
            BusinessConfig.model_validate({"business_profile": profile, "lead_management": {"retention_days": invalid}})
    assert BusinessConfig.model_validate({"business_profile": profile}).lead_management.retention_days is None


def _retention_world(session: Session, tenant: Tenant, other_tenant: Tenant) -> dict:
    policy = _business(session, tenant, "con-plazo", retention_days=30)
    no_policy = _business(session, tenant, "sin-plazo")
    foreign = _business(session, other_tenant, "ajeno-con-plazo", retention_days=30)
    old = _lead(session, policy, age_days=40)
    old_but_noted = _lead(session, policy, age_days=40)
    _note(session, old_but_noted, age_days=5)
    recent = _lead(session, policy, age_days=5)
    return {
        "policy": policy,
        "foreign": foreign,
        "old": old,
        "kept": [old_but_noted, recent, _lead(session, no_policy, age_days=400)],
        "foreign_old": _lead(session, foreign, age_days=40),
    }


def test_the_retention_job_is_a_dry_run_by_default(session, tenant, other_tenant):
    world = _retention_world(session, tenant, other_tenant)

    runs = {r.business_id: r for r in purge_expired_leads(session, now=NOW)}

    assert set(runs) == {str(world["policy"].id), str(world["foreign"].id)}  # only businesses with a policy
    assert (runs[str(world["policy"].id)].expired, runs[str(world["policy"].id)].deleted) == (1, 0)
    assert _exists(session, Lead, id=world["old"].id)
    assert session.scalars(select(LeadDeletionEvent)).all() == []


def test_the_retention_job_deletes_only_expired_leads_and_is_safe_to_rerun(session, tenant, other_tenant):
    world = _retention_world(session, tenant, other_tenant)

    runs = purge_expired_leads(session, now=NOW, apply=True, business_id=world["policy"].id)

    assert [(r.expired, r.deleted) for r in runs] == [(1, 1)]
    assert not _exists(session, Lead, id=world["old"].id)
    for lead in world["kept"]:  # a recent note, a recent lead, a business without a policy
        assert _exists(session, Lead, id=lead.id)
    assert _exists(session, Lead, id=world["foreign_old"].id)  # another business: not in this run
    event = session.scalars(select(LeadDeletionEvent)).one()
    assert (event.reason, event.actor_user_id, event.actor_email) == (LeadDeletionReason.RETENTION_EXPIRED, None, None)
    again = purge_expired_leads(session, now=NOW, apply=True, business_id=world["policy"].id)
    assert [(r.expired, r.deleted) for r in again] == [(0, 0)]


def test_a_retried_deletion_inside_the_job_returns_the_first_record(session, tenant):
    business = _business(session, tenant, "con-plazo", retention_days=30)
    lead = _lead(session, business, age_days=40)
    ids = {"tenant_id": tenant.id, "business_id": business.id, "lead_id": lead.id}

    first, deleted_now = delete_lead(session, **ids, reason=LeadDeletionReason.RETENTION_EXPIRED)
    again, deleted_again = delete_lead(session, **ids, reason=LeadDeletionReason.RETENTION_EXPIRED)

    assert deleted_now and not deleted_again and again.id == first.id


def test_the_cli_is_a_dry_run_unless_apply_is_given(monkeypatch, capsys, engine):
    calls = []
    monkeypatch.setattr(retention, "purge_expired_leads", lambda session, **kw: calls.append(kw["apply"]) or [])
    monkeypatch.setattr("app.dependencies.engine", engine)

    retention.main([])
    dry = json.loads(capsys.readouterr().out)
    retention.main(["--apply"])
    applied = json.loads(capsys.readouterr().out)

    assert calls == [False, True]
    assert (dry["apply"], applied["apply"]) == (False, True)
