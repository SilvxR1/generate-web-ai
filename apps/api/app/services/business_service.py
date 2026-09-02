from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.business import Business
from app.repositories.business import BusinessRepository
from app.schemas.business import BusinessWriteRequest


class SlugConflictError(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"A business with slug {slug!r} already exists for this tenant.")
        self.slug = slug


class BusinessNotFoundError(Exception):
    def __init__(self, business_id: UUID) -> None:
        super().__init__(f"No business {business_id} for this tenant.")
        self.business_id = business_id


class BusinessService:
    """Business rules for Business/BusinessConfig, kept independent of
    FastAPI so they're testable without an HTTP layer (see
    tests/test_business_service.py) and reusable between the create and
    update routes. Every method takes `tenant_id` explicitly and passes
    it straight to BusinessRepository — the tenant-isolation boundary
    lives one layer down, not duplicated here.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = BusinessRepository(session)

    def create(self, tenant_id: UUID, data: BusinessWriteRequest) -> Business:
        self._ensure_slug_available(tenant_id, data.slug)
        business = Business(tenant_id=tenant_id, **self._columns(data))
        return self.repo.add(business)

    def list(self, tenant_id: UUID) -> list[Business]:
        return self.repo.list(tenant_id)

    def get(self, tenant_id: UUID, business_id: UUID) -> Business:
        business = self.repo.get(tenant_id, business_id)
        if business is None:
            raise BusinessNotFoundError(business_id)
        return business

    def update(self, tenant_id: UUID, business_id: UUID, data: BusinessWriteRequest) -> Business:
        business = self.get(tenant_id, business_id)
        if data.slug != business.slug:
            self._ensure_slug_available(tenant_id, data.slug)
        for field, value in self._columns(data).items():
            setattr(business, field, value)
        self.session.flush()
        return business

    def delete(self, tenant_id: UUID, business_id: UUID) -> None:
        if not self.repo.delete(tenant_id, business_id):
            raise BusinessNotFoundError(business_id)

    def _ensure_slug_available(self, tenant_id: UUID, slug: str) -> None:
        if self.repo.list(tenant_id, slug=slug):
            raise SlugConflictError(slug)

    @staticmethod
    def _columns(data: BusinessWriteRequest) -> dict[str, object]:
        return {
            "name": data.name,
            "slug": data.slug,
            "vertical": data.vertical,
            "raw_description": data.raw_description,
            "status": data.status,
            "config": data.config.model_dump(mode="json") if data.config else None,
            "config_schema_version": data.config.schema_version if data.config else 1,
        }
