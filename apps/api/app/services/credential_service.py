from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.credential import Credential
from app.repositories.credential import CredentialRepository
from app.schemas.credential import CredentialCreate
from app.security.encryption import CredentialCipher


class CredentialService:
    """The one place plaintext secrets and the encryption key are allowed
    to meet. A plain CredentialRepository would let a caller construct a
    Credential row directly with a hand-encrypted (or unencrypted) value;
    routing creation through this service is what actually guarantees
    every stored value went through CredentialCipher."""

    def __init__(self, session: Session, cipher: CredentialCipher) -> None:
        self.repo = CredentialRepository(session)
        self.cipher = cipher

    def create(self, data: CredentialCreate) -> Credential:
        credential = Credential(
            tenant_id=data.tenant_id,
            integration_id=data.integration_id,
            encrypted_value=self.cipher.encrypt(data.secret),
            expires_at=data.expires_at,
        )
        return self.repo.add(credential)

    def reveal_secret(self, tenant_id: UUID, credential_id: UUID) -> str | None:
        credential = self.repo.get(tenant_id, credential_id)
        if credential is None:
            return None
        return self.cipher.decrypt(credential.encrypted_value)
