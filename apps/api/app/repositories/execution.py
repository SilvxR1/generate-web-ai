from app.db.models.execution import Execution
from app.repositories.base import TenantScopedRepository


class ExecutionRepository(TenantScopedRepository[Execution]):
    model = Execution
