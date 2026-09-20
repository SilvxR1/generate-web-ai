"""VisualIntent (P2.4) — WHAT a generated image should depict or accomplish,
kept separate from AssetPurpose, which says WHERE it will be used.

`AssetPurpose.HERO` tells an image model nothing about a subject; asked for a
"website hero" with only operational business text, Experiment 3's model drew
a webpage. A VisualIntent is resolved deterministically from real evidence and
never invents a business-specific subject:

- PRODUCT_GROUNDED   — depicts a real product from a real reference.
- SUBJECT_EDITORIAL  — a conceptual, category-level depiction of verified
                       offering categories. Not a documentary photo of real
                       products.
- ABSTRACT_BRAND     — abstract shape/texture/light expressing the brand
                       profile. No literal subject.
- ATMOSPHERIC        — mood through light, color and space. No literal
                       subject. The safe default when nothing is verified.

SUBJECT GROUNDING records how truthful the depicted subject is:

- GROUNDED   — taken from a real, authoritative reference.
- CONCEPTUAL — generated and representational. Makes no claim about real
               products, projects, customers or premises (abstract images and
               category-level depictions both belong here).
- UNKNOWN    — the required subject information is missing (e.g. a PRODUCT
               request with no real product image).

Deterministic rules only; no LLM, no image analysis.
"""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brand_profile import BrandVisualProfile
from app.domain.creative.brief import CreativeBriefAsset
from app.domain.creative.creative_context import CreativeContext
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, AssetPurpose, BrandStrategy

VISUAL_INTENT_VERSION = "p2.4-v1"


class VisualIntentKind(StrEnum):
    PRODUCT_GROUNDED = "product_grounded"
    SUBJECT_EDITORIAL = "subject_editorial"
    ABSTRACT_BRAND = "abstract_brand"
    ATMOSPHERIC = "atmospheric"


class SubjectGrounding(StrEnum):
    GROUNDED = "grounded"
    CONCEPTUAL = "conceptual"
    UNKNOWN = "unknown"


class VisualIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = VISUAL_INTENT_VERSION
    kind: VisualIntentKind
    grounding: SubjectGrounding
    # A code explaining why this intent was chosen — provenance, never prose.
    reason: str
    # Verified category-level subjects a SUBJECT_EDITORIAL image represents.
    subject_categories: list[str] = Field(default_factory=list)


_SURFACE_PURPOSES = frozenset({AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE})


def _has_real_product_image(assets: Sequence[CreativeBriefAsset]) -> bool:
    return any(
        asset.kind is AssetKind.IMAGE
        and asset.category is AssetCategory.PRODUCT
        and asset.origin is not AssetOrigin.GENERATED
        for asset in assets
    )


def resolve_visual_intent(
    *,
    purpose: AssetPurpose,
    brand_mode: BrandStrategy,
    context: CreativeContext,
    profile: BrandVisualProfile,
    assets: Sequence[CreativeBriefAsset],
) -> VisualIntent:
    # A NEW_DIRECTION is not constrained by the existing brand identity.
    has_brand = brand_mode is not BrandStrategy.NEW_DIRECTION and bool(profile.palette or profile.visual_style)

    if purpose is AssetPurpose.PRODUCT:
        if _has_real_product_image(assets):
            return VisualIntent(
                kind=VisualIntentKind.PRODUCT_GROUNDED,
                grounding=SubjectGrounding.GROUNDED,
                reason="real_product_reference_available",
            )
        return VisualIntent(
            kind=VisualIntentKind.PRODUCT_GROUNDED,
            grounding=SubjectGrounding.UNKNOWN,
            reason="product_purpose_without_a_real_product_image",
        )

    if purpose in _SURFACE_PURPOSES:
        return _abstract_or_atmospheric(has_brand, "surface_purpose_has_no_literal_subject")

    if context.subject_categories:
        return VisualIntent(
            kind=VisualIntentKind.SUBJECT_EDITORIAL,
            grounding=SubjectGrounding.CONCEPTUAL,
            reason="verified_subject_categories_available",
            subject_categories=list(context.subject_categories),
        )
    return _abstract_or_atmospheric(
        has_brand,
        "no_verified_subject_brand_profile_available" if has_brand else "no_verified_subject_no_brand_profile",
    )


def _abstract_or_atmospheric(has_brand: bool, reason: str) -> VisualIntent:
    kind = VisualIntentKind.ABSTRACT_BRAND if has_brand else VisualIntentKind.ATMOSPHERIC
    return VisualIntent(kind=kind, grounding=SubjectGrounding.CONCEPTUAL, reason=reason)
