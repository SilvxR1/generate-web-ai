from app.db.models.integration import Integration
from app.repositories.base import TenantScopedRepository


class IntegrationRepository(TenantScopedRepository[Integration]):
    model = Integration
