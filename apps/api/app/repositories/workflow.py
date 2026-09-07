from collections.abc import Sequence
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

    def list_for_businesses(self, tenant_id: UUID, business_ids: Sequence[UUID]) -> list[Workflow]:
        """Batch counterpart to `get_for_business`: every Workflow row
        for a set of businesses in one query, still ordered by creation
        so a caller picking the first match per `business_id` (see GET
        /business-summaries in app.routers.businesses) gets the same
        "the" workflow `get_for_business` would — without one query per
        business."""
        if not business_ids:
            return []
        stmt = (
            select(Workflow)
            .where(Workflow.tenant_id == tenant_id, Workflow.business_id.in_(business_ids))
            .order_by(Workflow.created_at)
        )
        return list(self.session.scalars(stmt).all())
