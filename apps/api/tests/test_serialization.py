"""ORM object -> Read schema serialization, including the one case that
matters most: a Credential's plaintext/encrypted secret must never appear
in a serialized Read schema."""

from app.db.models.business import Business
from app.db.models.credential import Credential
from app.db.models.integration import Integration
from app.db.models.tenant import Tenant
from app.domain.enums import IntegrationProvider, IntegrationStatus
from app.schemas.business import BusinessRead
from app.schemas.credential import CredentialRead
from app.schemas.tenant import TenantRead


def test_tenant_read_round_trips_from_orm(tenant: Tenant):
    read = TenantRead.model_validate(tenant)
    assert read.id == tenant.id
    assert read.name == "Acme Studio"

    dumped = read.model_dump(mode="json")
    assert dumped["name"] == "Acme Studio"
    assert "id" in dumped and "created_at" in dumped


def test_business_read_round_trips_from_orm(business: Business):
    read = BusinessRead.model_validate(business)
    dumped = read.model_dump(mode="json")

    assert dumped["name"] == business.name
    assert dumped["vertical"] == business.vertical.value
    assert dumped["tenant_id"] == str(business.tenant_id)


def test_credential_read_never_serializes_the_encrypted_value(session, tenant: Tenant, business: Business):
    integration = Integration(
        tenant_id=tenant.id,
        business_id=business.id,
        provider=IntegrationProvider.SLACK,
        status=IntegrationStatus.CONNECTED,
    )
    session.add(integration)
    session.flush()

    credential = Credential(
        tenant_id=tenant.id,
        integration_id=integration.id,
        encrypted_value="gAAAAA-fake-fernet-token-standing-in-for-a-real-one",
    )
    session.add(credential)
    session.flush()

    read = CredentialRead.model_validate(credential)
    dumped = read.model_dump(mode="json")

    assert "encrypted_value" not in dumped
    assert "secret" not in dumped
    assert set(dumped.keys()) == {"id", "tenant_id", "integration_id", "expires_at", "created_at", "updated_at"}
