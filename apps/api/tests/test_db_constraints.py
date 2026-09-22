"""Constraints enforced by the database itself, not just by Pydantic —
these must hold even for a write that bypasses the schema layer."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.business import Business
from app.db.models.execution import Execution
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.db.models.website import Website
from app.db.models.workflow import Workflow
from app.db.models.workflow_version import WorkflowVersion
from app.domain.enums import (
    ConfigOrigin,
    DeployTarget,
    ExecutionStatus,
    ExecutionType,
    UserRole,
    WebsiteStatus,
    WorkflowStatus,
    WorkflowVersionStatus,
)


def test_website_business_id_is_unique(session, tenant: Tenant, business: Business):
    def _new_website() -> Website:
        return Website(
            tenant_id=tenant.id,
            business_id=business.id,
            deploy_target=DeployTarget.CLOUDFLARE,
            status=WebsiteStatus.DRAFT,
        )

    session.add(_new_website())
    session.flush()

    session.add(_new_website())
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_user_email_unique_globally(session, tenant: Tenant, other_tenant: Tenant):
    """A2: User is no longer tenant-scoped (the architectural correction
    that replaced "User -> exactly one Tenant" with an explicit
    TenantAccess join table — see test_tenant_access_unique_per_user_and_tenant
    below), so email uniqueness is now global (uq_users_email), not
    per-tenant. A second User row can never reuse an email regardless of
    which tenant(s) either one has access to."""
    session.add(User(email="team@acme.studio"))
    session.flush()

    session.add(User(email="team@acme.studio"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_tenant_access_unique_per_user_and_tenant(session, tenant: Tenant, other_tenant: Tenant):
    """The same User row may hold a TenantAccess grant for more than one
    Tenant (that's the entire point of the join table), but never two
    grants for the *same* tenant (uq_tenant_access_user_tenant) — and
    merely knowing a tenant's id grants nothing without a row here (see
    app.dependencies.get_current_tenant_id)."""
    user = User(email="team@acme.studio")
    session.add(user)
    session.flush()

    session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
    session.flush()

    # Same user, same tenant again -> rejected.
    session.add(TenantAccess(user_id=user.id, tenant_id=tenant.id, role=UserRole.OPERATOR))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    # Same user, a different tenant -> allowed.
    session.add(TenantAccess(user_id=user.id, tenant_id=other_tenant.id, role=UserRole.OPERATOR))
    session.flush()


def test_workflow_version_number_unique_per_workflow(session, tenant: Tenant, business: Business):
    workflow = Workflow(
        tenant_id=tenant.id,
        business_id=business.id,
        name="Lead capture",
        status=WorkflowStatus.DRAFT,
        local_workflow_id="lead-capture",
    )
    session.add(workflow)
    session.flush()

    session.add(
        WorkflowVersion(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            version=1,
            definition={"steps": []},
            created_by=ConfigOrigin.AI,
            status=WorkflowVersionStatus.DRAFT,
        )
    )
    session.flush()

    session.add(
        WorkflowVersion(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            version=1,
            definition={"steps": []},
            created_by=ConfigOrigin.HUMAN,
            status=WorkflowVersionStatus.DRAFT,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_execution_check_constraint_rejects_mismatched_target(session, tenant: Tenant, business: Business):
    """Bypasses the Pydantic layer entirely to prove the CHECK constraint
    itself — not just the schema validator — blocks an inconsistent row."""
    session.add(
        Execution(
            tenant_id=tenant.id,
            business_id=business.id,
            type=ExecutionType.WORKFLOW_RUN,
            status=ExecutionStatus.PENDING,
            workflow_id=None,
            website_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_execution_check_constraint_accepts_consistent_workflow_run(session, tenant: Tenant, business: Business):
    workflow = Workflow(
        tenant_id=tenant.id,
        business_id=business.id,
        name="Lead capture",
        status=WorkflowStatus.DRAFT,
        local_workflow_id="lead-capture",
    )
    session.add(workflow)
    session.flush()

    session.add(
        Execution(
            tenant_id=tenant.id,
            business_id=business.id,
            type=ExecutionType.WORKFLOW_RUN,
            status=ExecutionStatus.PENDING,
            workflow_id=workflow.id,
        )
    )
    session.flush()
