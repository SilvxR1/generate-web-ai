"""BusinessService (app.services.business_service): the "Persistence"
bullet of the business-configuration-system phase — create, retrieve,
update config, delete, tenant relationship — exercised directly against
the repository/service layer, independent of the HTTP/API layer (see
tests/test_business_api_isolation.py for that, and its docstring for why
the API-layer boundary isn't real authentication yet)."""

import uuid

import pytest

from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG, BusinessConfig
from app.domain.enums import BusinessStatus, BusinessVertical
from app.schemas.business import BusinessWriteRequest
from app.services.business_service import BusinessNotFoundError, BusinessService, SlugConflictError


def _write_request(**overrides: object) -> BusinessWriteRequest:
    data = {
        "name": "Sacri Barber",
        "slug": "sacri-barber",
        "vertical": BusinessVertical.OTHER,
        "raw_description": "Barberia clasica en el centro de la ciudad con mas de cinco anos de trayectoria.",
        "status": BusinessStatus.DRAFT,
        "config": None,
    }
    data.update(overrides)
    return BusinessWriteRequest(**data)


def test_create_business_without_config(session, tenant):
    service = BusinessService(session)

    business = service.create(tenant.id, _write_request())

    assert business.id is not None
    assert business.tenant_id == tenant.id
    assert business.config is None
    assert business.config_schema_version == 1


def test_create_business_with_config_persists_it_as_json(session, tenant):
    service = BusinessService(session)
    request = _write_request(
        name="Reforma Casa Valencia",
        slug="reforma-casa-valencia",
        vertical=BusinessVertical.HOME_RENOVATION,
        config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
    )

    business = service.create(tenant.id, request)

    assert isinstance(business.config, dict)
    assert business.config["business_profile"]["slug"] == "reforma-casa-valencia"
    assert business.config_schema_version == 1


def test_retrieve_business(session, tenant):
    service = BusinessService(session)
    created = service.create(tenant.id, _write_request())

    fetched = service.get(tenant.id, created.id)

    assert fetched.id == created.id
    assert fetched.name == "Sacri Barber"


def test_retrieve_nonexistent_business_raises(session, tenant):
    service = BusinessService(session)

    with pytest.raises(BusinessNotFoundError):
        service.get(tenant.id, uuid.uuid4())


def test_update_business_config(session, tenant):
    service = BusinessService(session)
    business = service.create(tenant.id, _write_request())
    assert business.config is None

    updated = service.update(tenant.id, business.id, _write_request(config=EXAMPLE_REFORMA_VALENCIA_CONFIG))

    assert updated.id == business.id
    assert updated.config is not None
    assert updated.config["business_profile"]["name"] == "Reforma Casa Valencia"

    # And it round-trips back into the domain type cleanly.
    restored = BusinessConfig.model_validate(updated.config)
    assert restored == EXAMPLE_REFORMA_VALENCIA_CONFIG


def test_update_nonexistent_business_raises(session, tenant):
    service = BusinessService(session)

    with pytest.raises(BusinessNotFoundError):
        service.update(tenant.id, uuid.uuid4(), _write_request())


def test_create_rejects_duplicate_slug_within_tenant(session, tenant):
    service = BusinessService(session)
    service.create(tenant.id, _write_request(slug="sacri-barber"))

    with pytest.raises(SlugConflictError):
        service.create(tenant.id, _write_request(name="Sacri Barber 2", slug="sacri-barber"))


def test_same_slug_allowed_across_different_tenants(session, tenant, other_tenant):
    service = BusinessService(session)
    service.create(tenant.id, _write_request(slug="sacri-barber"))

    # Should not raise — slugs are unique per tenant, not globally.
    other = service.create(other_tenant.id, _write_request(slug="sacri-barber"))
    assert other.slug == "sacri-barber"


def test_delete_business(session, tenant):
    service = BusinessService(session)
    business = service.create(tenant.id, _write_request())

    service.delete(tenant.id, business.id)

    with pytest.raises(BusinessNotFoundError):
        service.get(tenant.id, business.id)


def test_delete_nonexistent_business_raises(session, tenant):
    service = BusinessService(session)

    with pytest.raises(BusinessNotFoundError):
        service.delete(tenant.id, uuid.uuid4())


def test_list_businesses_scoped_to_tenant(session, tenant, other_tenant):
    service = BusinessService(session)
    service.create(tenant.id, _write_request(slug="business-a"))
    service.create(other_tenant.id, _write_request(slug="business-b"))

    tenant_results = service.list(tenant.id)

    assert len(tenant_results) == 1
    assert tenant_results[0].tenant_id == tenant.id


def test_created_business_relates_to_its_tenant(session, tenant):
    service = BusinessService(session)
    business = service.create(tenant.id, _write_request())

    assert business.tenant is tenant
    assert business in tenant.businesses
