from app.db.models.business import Business
from app.repositories.base import TenantScopedRepository


class BusinessRepository(TenantScopedRepository[Business]):
    model = Business
