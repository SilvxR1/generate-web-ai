from uuid import UUID

from sqlalchemy import select

from app.db.models.business_review import BusinessReview
from app.repositories.base import TenantScopedRepository


class BusinessReviewRepository(TenantScopedRepository[BusinessReview]):
    model = BusinessReview

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[BusinessReview]:
        """Every review imported/provided for this business, most recent
        first — same tenant+business scoping as every other
        *_for_business lookup (see LeadRepository.list_for_business).
        Reads `body` back verbatim; nothing here ever rewrites it."""
        stmt = (
            select(BusinessReview)
            .where(BusinessReview.tenant_id == tenant_id, BusinessReview.business_id == business_id)
            .order_by(BusinessReview.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, review_id: UUID) -> BusinessReview | None:
        stmt = select(BusinessReview).where(
            BusinessReview.tenant_id == tenant_id,
            BusinessReview.business_id == business_id,
            BusinessReview.id == review_id,
        )
        return self.session.scalars(stmt).first()
