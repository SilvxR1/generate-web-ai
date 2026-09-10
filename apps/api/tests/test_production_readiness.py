"""get_production_readiness (app.publishing.readiness) + its HTTP
boundary (GET /businesses/{id}/production-readiness): only
website_config/hosting_provider can ever be `blocking`, every other
check (legal profile, custom domain, published) stays informational
regardless of how incomplete it is — P0's explicit "only real technical
blockers should prevent publishing... do NOT invent legal blocking
rules" constraint. Also covers has_blocking_issues tracking exactly
those two checks, and tenant isolation at the HTTP layer."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.dependencies import get_session
from app.main import app
from app.publishing.readiness import get_production_readiness
from app.publishing.service import publish_website
from tests.test_website_publish_service import _FAKE_ARTIFACT, FakePublisher, _site_config


@pytest.fixture(autouse=True)
def _fake_build(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.publishing.service.build_site", lambda site_config: _FAKE_ARTIFACT)


def _checks_by_id(report):
    return {check.id: check for check in report.checks}


# --- service: individual checks ----------------------------------------------


def test_a_brand_new_business_has_no_ready_checks_and_is_blocked(
    session: Session, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    checks = _checks_by_id(report)
    assert checks["website_config"].ready is False
    assert checks["website_config"].blocking is True
    assert checks["hosting_provider"].ready is False
    assert checks["hosting_provider"].blocking is True
    assert report.has_blocking_issues is True


def test_website_config_is_ready_once_the_business_has_a_config(session: Session, business: Business):
    business.config = {
        "schema_version": 1,
        "business_profile": {"name": business.name, "slug": business.slug, "industry": "other"},
    }
    session.flush()

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert _checks_by_id(report)["website_config"].ready is True


def test_hosting_provider_ready_when_cloudflare_is_configured(
    session: Session, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cloudflare_account_id", "acct-1")
    monkeypatch.setattr(settings, "cloudflare_api_token", "token-1")

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert _checks_by_id(report)["hosting_provider"].ready is True


def test_no_blocking_issues_once_both_technical_checks_are_ready(
    session: Session, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cloudflare_account_id", "acct-1")
    monkeypatch.setattr(settings, "cloudflare_api_token", "token-1")
    business.config = {
        "schema_version": 1,
        "business_profile": {"name": business.name, "slug": business.slug, "industry": "other"},
    }
    session.flush()

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert report.has_blocking_issues is False


def test_published_check_is_informational_never_blocking(session: Session, business: Business):
    report_before = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert _checks_by_id(report_before)["published"].ready is False
    assert _checks_by_id(report_before)["published"].blocking is False

    publish_website(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        site_config=_site_config(),
        publisher=FakePublisher(),
    )

    report_after = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert _checks_by_id(report_after)["published"].ready is True
    assert _checks_by_id(report_after)["published"].blocking is False


def test_legal_profile_incompleteness_never_sets_blocking_even_when_not_ready(
    session: Session, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "cloudflare_account_id", None)
    monkeypatch.setattr(settings, "cloudflare_api_token", None)
    business.config = {
        "schema_version": 1,
        "business_profile": {"name": business.name, "slug": business.slug, "industry": "other"},
        "legal_profile": {"legal_name": "Acme S.L."},  # missing address + privacy_contact_email
    }
    session.flush()

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    legal_check = _checks_by_id(report)["legal_profile"]
    assert legal_check.ready is False
    assert legal_check.blocking is False
    # has_blocking_issues is True here only because hosting_provider (a
    # genuine technical blocker, pinned unconfigured above) isn't ready
    # — never because of the incomplete legal profile.
    assert report.has_blocking_issues is True


def test_legal_profile_ready_once_the_key_fields_are_filled_in(session: Session, business: Business):
    business.config = {
        "schema_version": 1,
        "business_profile": {"name": business.name, "slug": business.slug, "industry": "other"},
        "legal_profile": {
            "legal_name": "Acme S.L.",
            "address": {"street_address": "Calle Mayor 1", "locality": "Valencia", "country": "ES"},
            "privacy_contact_email": "privacy@acme.example",
        },
    }
    session.flush()

    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    legal_check = _checks_by_id(report)["legal_profile"]
    assert legal_check.ready is True
    assert legal_check.blocking is False


def test_custom_domain_check_is_informational_and_reflects_no_domain_attached(session: Session, business: Business):
    report = get_production_readiness(session=session, tenant_id=business.tenant_id, business_id=business.id)

    domain_check = _checks_by_id(report)["custom_domain"]
    assert domain_check.ready is False
    assert domain_check.blocking is False


# --- API boundary --------------------------------------------------------------


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_get_production_readiness_returns_the_checklist(client: TestClient, tenant: Tenant, business: Business):
    response = client.get(f"/businesses/{business.id}/production-readiness", headers={"X-Tenant-Id": str(tenant.id)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert "checks" in body
    assert "has_blocking_issues" in body
    check_ids = {check["id"] for check in body["checks"]}
    assert check_ids == {"website_config", "hosting_provider", "published", "legal_profile", "custom_domain"}


def test_production_readiness_never_leaks_across_tenants(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, business: Business
):
    response = client.get(
        f"/businesses/{business.id}/production-readiness", headers={"X-Tenant-Id": str(other_tenant.id)}
    )

    assert response.status_code == 404


def test_production_readiness_requires_a_tenant_header(client: TestClient, business: Business):
    response = client.get(f"/businesses/{business.id}/production-readiness")

    assert response.status_code == 422
