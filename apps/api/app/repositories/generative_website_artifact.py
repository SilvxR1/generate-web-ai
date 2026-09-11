from uuid import UUID

from sqlalchemy import select

from app.db.models.generative_website_artifact import GenerativeWebsiteArtifact
from app.repositories.base import TenantScopedRepository


class GenerativeWebsiteArtifactRepository(TenantScopedRepository[GenerativeWebsiteArtifact]):
    model = GenerativeWebsiteArtifact

    def get_for_draft(
        self, tenant_id: UUID, business_id: UUID, website_draft_id: UUID
    ) -> GenerativeWebsiteArtifact | None:
        stmt = select(GenerativeWebsiteArtifact).where(
            GenerativeWebsiteArtifact.tenant_id == tenant_id,
            GenerativeWebsiteArtifact.business_id == business_id,
            GenerativeWebsiteArtifact.website_draft_id == website_draft_id,
        )
        return self.session.scalars(stmt).first()
