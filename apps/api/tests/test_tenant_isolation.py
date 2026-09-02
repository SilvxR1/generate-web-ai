"""Tenant isolation: a repository call scoped to tenant A must never see
or touch tenant B's rows, even when the row id is known."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.website import Website
from app.domain.enums import BusinessStatus, BusinessVertical, DeployTarget, WebsiteStatus
from app.repositories.business import BusinessRepository
from app.repositories.website import WebsiteRepository


def test_get_scoped_to_owning_tenant_returns_none_for_other_tenant(
    session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    repo = BusinessRepository(session)

    assert repo.get(tenant.id, business.id) is not None
    assert repo.get(other_tenant.id, business.id) is None


def test_list_scoped_to_tenant_excludes_other_tenants_rows(
    session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    other_business = Business(
        tenant_id=other_tenant.id,
        name="Otra Empresa",
        slug="otra-empresa",
        vertical=BusinessVertical.CLINIC,
        raw_description="Clinica dental con dos sedes en Madrid capital y alrededores.",
        status=BusinessStatus.DRAFT,
    )
    session.add(other_business)
    session.flush()

    repo = BusinessRepository(session)

    tenant_a_results = repo.list(tenant.id)
    tenant_b_results = repo.list(other_tenant.id)

    assert [b.id for b in tenant_a_results] == [business.id]
    assert [b.id for b in tenant_b_results] == [other_business.id]


def test_delete_scoped_to_tenant_cannot_delete_other_tenants_row(
    session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    repo = BusinessRepository(session)

    deleted = repo.delete(other_tenant.id, business.id)

    assert deleted is False
    assert repo.get(tenant.id, business.id) is not None


def test_website_tenant_id_must_match_business_tenant_in_practice(
    session, tenant: Tenant, other_tenant: Tenant, business: Business
):
    """The mixin doesn't enforce cross-row consistency by itself (that's
    an application-level responsibility) — this documents the invariant a
    service layer must uphold: a Website's tenant_id always matches its
    Business's tenant_id, never the other id's tenant."""
    website = Website(
        tenant_id=tenant.id,
        business_id=business.id,
        deploy_target=DeployTarget.CLOUDFLARE,
        status=WebsiteStatus.DRAFT,
    )
    session.add(website)
    session.flush()

    repo = WebsiteRepository(session)
    assert repo.get_by_business(tenant.id, business.id) is not None
    assert repo.get_by_business(other_tenant.id, business.id) is None


def test_business_requires_a_tenant(session):
    orphan = Business(
        name="Sin Tenant",
        slug="sin-tenant",
        vertical=BusinessVertical.AGENCY,
        raw_description="Agencia de marketing digital especializada en negocios locales.",
        status=BusinessStatus.DRAFT,
    )
    session.add(orphan)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
