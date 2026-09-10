from uuid import UUID

from sqlalchemy import select

from app.db.models.website_version import WebsiteVersion
from app.repositories.base import TenantScopedRepository


class WebsiteVersionRepository(TenantScopedRepository[WebsiteVersion]):
    model = WebsiteVersion

    def list_for_business(self, tenant_id: UUID, business_id: UUID) -> list[WebsiteVersion]:
        """Most recent first — the order Studio's version history and
        app.publishing.rollback's "what's currently the newest version"
        check both rely on."""
        stmt = (
            select(WebsiteVersion)
            .where(WebsiteVersion.tenant_id == tenant_id, WebsiteVersion.business_id == business_id)
            .order_by(WebsiteVersion.published_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, version_id: UUID) -> WebsiteVersion | None:
        stmt = select(WebsiteVersion).where(
            WebsiteVersion.tenant_id == tenant_id,
            WebsiteVersion.business_id == business_id,
            WebsiteVersion.id == version_id,
        )
        return self.session.scalars(stmt).first()
