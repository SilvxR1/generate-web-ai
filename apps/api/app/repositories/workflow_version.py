from uuid import UUID

from sqlalchemy import func, select

from app.db.models.workflow_version import WorkflowVersion
from app.repositories.base import TenantScopedRepository


class WorkflowVersionRepository(TenantScopedRepository[WorkflowVersion]):
    model = WorkflowVersion

    def next_version_number(self, tenant_id: UUID, workflow_id: UUID) -> int:
        stmt = select(func.max(WorkflowVersion.version)).where(
            WorkflowVersion.tenant_id == tenant_id, WorkflowVersion.workflow_id == workflow_id
        )
        current_max = self.session.scalar(stmt)
        return (current_max or 0) + 1
