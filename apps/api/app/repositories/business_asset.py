from uuid import UUID

from sqlalchemy import select

from app.db.models.business_asset import BusinessAsset
from app.domain.enums import AssetCategory, AssetOrigin
from app.repositories.base import TenantScopedRepository


class BusinessAssetRepository(TenantScopedRepository[BusinessAsset]):
    model = BusinessAsset

    def list_for_business(
        self,
        tenant_id: UUID,
        business_id: UUID,
        *,
        category: AssetCategory | None = None,
        origin: AssetOrigin | None = None,
    ) -> list[BusinessAsset]:
        """Every asset in this business's library, most recent first —
        the same tenant+business scoping every other *_for_business
        lookup in this codebase uses (see LeadRepository.list_for_business).
        `category`/`origin` are optional narrowing filters (e.g. "just
        real photos" for app.domain.creative.brief's real-asset
        preference), never a substitute for the tenant/business scope
        itself."""
        stmt = (
            select(BusinessAsset)
            .where(BusinessAsset.tenant_id == tenant_id, BusinessAsset.business_id == business_id)
            .order_by(BusinessAsset.created_at.desc())
        )
        if category is not None:
            stmt = stmt.where(BusinessAsset.category == category)
        if origin is not None:
            stmt = stmt.where(BusinessAsset.origin == origin)
        return list(self.session.scalars(stmt).all())

    def get_for_business(self, tenant_id: UUID, business_id: UUID, asset_id: UUID) -> BusinessAsset | None:
        """Scoped through tenant_id AND business_id AND asset_id all
        matching — the same three-way scoping LeadRepository.get_for_business
        uses, so an asset can only be read/mutated via its own business's
        route, never another business the same tenant owns."""
        stmt = select(BusinessAsset).where(
            BusinessAsset.tenant_id == tenant_id,
            BusinessAsset.business_id == business_id,
            BusinessAsset.id == asset_id,
        )
        return self.session.scalars(stmt).first()
