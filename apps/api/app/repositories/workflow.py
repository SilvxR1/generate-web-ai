from uuid import UUID

from sqlalchemy import select

from app.db.models.workflow import Workflow
from app.repositories.base import TenantScopedRepository


class WorkflowRepository(TenantScopedRepository[Workflow]):
    model = Workflow

    def get_for_business(self, tenant_id: UUID, business_id: UUID) -> Workflow | None:
        """The generated-automation MVP only ever produces one workflow
        per business (lead-capture) — this is "the" Workflow row
        app.automation.activation persists activation state on. Ordered
        by creation so a future business with more than one generated
        workflow still gets a stable, deterministic answer rather than
        an arbitrary row."""
        stmt = (
            select(Workflow)
            .where(Workflow.tenant_id == tenant_id, Workflow.business_id == business_id)
            .order_by(Workflow.created_at)
        )
        return self.session.scalars(stmt).first()
