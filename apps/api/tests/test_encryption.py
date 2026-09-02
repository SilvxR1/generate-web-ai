"""CredentialCipher and CredentialService: real Fernet encryption, not a
stub — the encrypted value stored must never equal the plaintext, must
decrypt back to it under the right key, and must not decrypt under the
wrong one."""

import pytest

from app.db.models.integration import Integration
from app.domain.enums import IntegrationProvider, IntegrationStatus
from app.schemas.credential import CredentialCreate
from app.security.encryption import CredentialCipher
from app.services.credential_service import CredentialService


def test_encrypt_decrypt_round_trip():
    cipher = CredentialCipher(CredentialCipher.generate_key())

    token = cipher.encrypt("gmail-oauth-refresh-token")

    assert token != "gmail-oauth-refresh-token"
    assert cipher.decrypt(token) == "gmail-oauth-refresh-token"


def test_decrypt_fails_with_wrong_key():
    cipher_a = CredentialCipher(CredentialCipher.generate_key())
    cipher_b = CredentialCipher(CredentialCipher.generate_key())

    token = cipher_a.encrypt("hubspot-api-key")

    with pytest.raises(ValueError, match="could not be decrypted"):
        cipher_b.decrypt(token)


def test_credential_service_stores_ciphertext_not_plaintext(session, tenant, business):
    integration = Integration(
        tenant_id=tenant.id,
        business_id=business.id,
        provider=IntegrationProvider.HUBSPOT,
        status=IntegrationStatus.CONNECTED,
    )
    session.add(integration)
    session.flush()

    cipher = CredentialCipher(CredentialCipher.generate_key())
    service = CredentialService(session, cipher)

    credential = service.create(
        CredentialCreate(tenant_id=tenant.id, integration_id=integration.id, secret="hubspot-api-key-plaintext")
    )

    assert credential.encrypted_value != "hubspot-api-key-plaintext"
    assert service.reveal_secret(tenant.id, credential.id) == "hubspot-api-key-plaintext"


def test_credential_service_reveal_scoped_to_tenant(session, tenant, other_tenant, business):
    integration = Integration(
        tenant_id=tenant.id,
        business_id=business.id,
        provider=IntegrationProvider.GMAIL,
        status=IntegrationStatus.CONNECTED,
    )
    session.add(integration)
    session.flush()

    cipher = CredentialCipher(CredentialCipher.generate_key())
    service = CredentialService(session, cipher)
    credential_data = CredentialCreate(tenant_id=tenant.id, integration_id=integration.id, secret="secret-value")
    credential = service.create(credential_data)

    assert service.reveal_secret(other_tenant.id, credential.id) is None
