"""The trusted business inputs a site is built and judged against.

Shared by the generative worker intake and R5 supervised source imports
(moved here from app.worker.intake so the draft approval/publish gates can
use it without an import cycle). Derived exactly like the generative route
does: stored BusinessConfig, available assets, visible reviews,
tenant-scoped. `business_truth_sha256` is the identity a plan, a build and
an approval bind to: any material BusinessTruth change changes it.
"""

import hashlib
import json
import uuid

from sqlalchemy.orm import Session

from app.domain.business_config import BusinessConfig
from app.domain.business_truth import BusinessTruth


class BusinessInputsError(Exception):
    """The business has no usable configuration."""


def load_business_inputs(
    session: Session, *, tenant_id: uuid.UUID, business_id: uuid.UUID
) -> tuple[BusinessConfig, BusinessTruth]:
    from app.db.models.business import Business
    from app.domain.business_truth import derive_business_truth
    from app.domain.creative import build_creative_brief
    from app.repositories.business_asset import BusinessAssetRepository
    from app.repositories.business_review import BusinessReviewRepository

    business = session.get(Business, business_id)
    if business is None or business.tenant_id != tenant_id or business.config is None:
        raise BusinessInputsError("business has no configuration")
    config = BusinessConfig.model_validate(business.config)
    assets = BusinessAssetRepository(session).list_for_business(tenant_id, business_id)
    brief = build_creative_brief(business_config=config, assets=assets)
    truth = derive_business_truth(
        business_config=config,
        assets=brief.available_assets,
        reviews=BusinessReviewRepository(session).list_for_business(tenant_id, business_id),
    )
    return config, truth


def business_truth_sha256(truth: BusinessTruth) -> str:
    data = json.dumps(truth.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()
