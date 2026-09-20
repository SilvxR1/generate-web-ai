"""GenerationReferenceStrategy (P2.3) — decides which business assets MAY be
sent to an image-generation model as visual references, which MUST NOT,
and whether the request needs a reference-conditioned model at all.

Why: two real production generations showed that sending the complete
official logo to a reference-conditioned model makes the model reproduce
it (and its lettering) regardless of prompt semantics. `having an asset`
does not imply `the provider should receive it`; BusinessAsset is not
GenerationReferenceAsset.

Rules (deterministic, purpose- and brand-mode-aware):

- The official logo is an authoritative BRAND SOURCE. It informs the
  BrandVisualProfile and is never a provider reference. The real logo is
  rendered by the website layer, not recreated by an image model.
- HERO / BACKGROUND / TEXTURE: no visual reference. Brand identity reaches
  the model as text (palette/style from the profile).
- SECTION / EDITORIAL: real business photography may be sent as an
  optional STYLE reference (mood/lighting), never for NEW_DIRECTION (a new
  direction must not be constrained by references) and never team photos
  (people's likenesses) or unclassified assets.
- PRODUCT: real product imagery is a required PRODUCT reference (subject
  fidelity). With no real product image the request is unsatisfiable —
  the system never invents a product.
- Only image assets qualify; unavailable assets never reach the brief;
  LOW_QUALITY and previously GENERATED assets are never sent.

"Authoritative" means "do not silently replace or falsify this asset". It
does NOT mean "always send it to the model".
"""

from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brand_profile import is_official_logo
from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.creative.spec import ReferenceSpec, ReferenceUsage
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, AssetPurpose, BrandStrategy

_MAX_PRODUCT_REFERENCES = 3
_MAX_STYLE_REFERENCES = 2
_MAX_WITHHELD_RECORDED = 30

_OPTIONAL_STYLE_PURPOSES = frozenset({AssetPurpose.SECTION, AssetPurpose.EDITORIAL})
_STYLE_CATEGORIES = frozenset(
    {
        AssetCategory.HERO_CANDIDATE,
        AssetCategory.PRODUCT,
        AssetCategory.PROJECT,
        AssetCategory.FACILITY,
        AssetCategory.GALLERY,
        AssetCategory.BEFORE,
        AssetCategory.AFTER,
    }
)
_STYLE_PRIORITY = {AssetCategory.HERO_CANDIDATE: 0, AssetCategory.PRODUCT: 1}

PRODUCT_REFERENCE_MISSING = "product_reference_missing"


class ReferencePolicy(StrEnum):
    NO_VISUAL_REFERENCE = "no_visual_reference"
    OPTIONAL_STYLE_REFERENCE = "optional_style_reference"
    REQUIRED_SUBJECT_REFERENCE = "required_subject_reference"


class WithheldReason(StrEnum):
    LOGO_INFORMS_BRAND_PROFILE = "logo_informs_brand_profile_only"
    NOT_AN_IMAGE = "not_an_image"
    LOW_QUALITY = "low_quality"
    GENERATED_ASSET = "generated_asset_not_used_as_reference"
    NOT_USED_FOR_PURPOSE = "not_used_for_purpose"
    NEW_DIRECTION_UNCONSTRAINED = "new_direction_is_not_constrained_by_references"
    PEOPLE_LIKENESS = "team_photo_not_sent_to_generation_model"
    UNCLASSIFIED = "unclassified_asset_not_sent_to_generation_model"


class WithheldAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID
    reason: WithheldReason


class ReferenceStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: ReferencePolicy
    # Ranked; the provider adapter resolves them in order within the
    # selected model's own limit.
    provider_reference_candidates: list[ReferenceSpec] = Field(default_factory=list)
    requires_visual_reference: bool = False
    # Real, non-generated, non-low-quality business assets: never silently
    # replaced or falsified. Says nothing about whether they are sent.
    authoritative_asset_ids: list[UUID] = Field(default_factory=list)
    withheld: list[WithheldAsset] = Field(default_factory=list)
    # Set when the request can't be satisfied honestly (e.g. PRODUCT with no
    # real product image) — the caller must not generate.
    unsatisfiable_reason: str | None = None


def is_authoritative_asset(asset: CreativeBriefAsset) -> bool:
    if is_official_logo(asset):
        return True
    return asset.origin is not AssetOrigin.GENERATED and asset.category is not AssetCategory.LOW_QUALITY


def _spec(asset: CreativeBriefAsset, usage: ReferenceUsage) -> ReferenceSpec:
    return ReferenceSpec(asset_id=asset.id, usage=usage, asset_kind=asset.kind, asset_category=asset.category)


def decide_reference_strategy(brief: CreativeBrief, assets: Sequence[CreativeBriefAsset]) -> ReferenceStrategy:
    purpose, mode = brief.asset_purpose, brief.brand_strategy
    withheld: list[WithheldAsset] = []
    authoritative: list[UUID] = []
    eligible: list[CreativeBriefAsset] = []

    def hold(asset: CreativeBriefAsset, reason: WithheldReason) -> None:
        withheld.append(WithheldAsset(asset_id=asset.id, reason=reason))

    for asset in assets:
        if is_authoritative_asset(asset):
            authoritative.append(asset.id)
        if is_official_logo(asset):
            hold(asset, WithheldReason.LOGO_INFORMS_BRAND_PROFILE)
        elif asset.kind is not AssetKind.IMAGE:
            hold(asset, WithheldReason.NOT_AN_IMAGE)
        elif asset.category is AssetCategory.LOW_QUALITY:
            hold(asset, WithheldReason.LOW_QUALITY)
        elif asset.origin is AssetOrigin.GENERATED:
            hold(asset, WithheldReason.GENERATED_ASSET)
        else:
            eligible.append(asset)

    references: list[ReferenceSpec] = []
    policy = ReferencePolicy.NO_VISUAL_REFERENCE
    requires = False
    unsatisfiable: str | None = None

    if purpose is AssetPurpose.PRODUCT:
        products = [asset for asset in eligible if asset.category is AssetCategory.PRODUCT]
        references = [_spec(asset, ReferenceUsage.PRODUCT) for asset in products[:_MAX_PRODUCT_REFERENCES]]
        for asset in eligible:
            if asset not in products[:_MAX_PRODUCT_REFERENCES]:
                hold(asset, WithheldReason.NOT_USED_FOR_PURPOSE)
        policy = ReferencePolicy.REQUIRED_SUBJECT_REFERENCE
        requires = True
        if not references:
            unsatisfiable = PRODUCT_REFERENCE_MISSING
    elif purpose in _OPTIONAL_STYLE_PURPOSES:
        if mode is BrandStrategy.NEW_DIRECTION:
            for asset in eligible:
                hold(asset, WithheldReason.NEW_DIRECTION_UNCONSTRAINED)
        else:
            usable: list[CreativeBriefAsset] = []
            for asset in eligible:
                if asset.category is AssetCategory.TEAM:
                    hold(asset, WithheldReason.PEOPLE_LIKENESS)
                elif asset.category not in _STYLE_CATEGORIES:
                    hold(asset, WithheldReason.UNCLASSIFIED)
                else:
                    usable.append(asset)
            usable.sort(key=lambda asset: _STYLE_PRIORITY.get(asset.category, 2))  # stable: caller order kept
            references = [_spec(asset, ReferenceUsage.STYLE) for asset in usable[:_MAX_STYLE_REFERENCES]]
            for asset in usable[_MAX_STYLE_REFERENCES:]:
                hold(asset, WithheldReason.NOT_USED_FOR_PURPOSE)
            if references:
                policy = ReferencePolicy.OPTIONAL_STYLE_REFERENCE
    else:
        for asset in eligible:
            hold(asset, WithheldReason.NOT_USED_FOR_PURPOSE)

    return ReferenceStrategy(
        policy=policy,
        provider_reference_candidates=references,
        requires_visual_reference=requires,
        authoritative_asset_ids=authoritative,
        withheld=withheld[:_MAX_WITHHELD_RECORDED],
        unsatisfiable_reason=unsatisfiable,
    )
