from app.db.models.credential import Credential
from app.repositories.base import TenantScopedRepository


class CredentialRepository(TenantScopedRepository[Credential]):
    model = Credential
