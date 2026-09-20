"""CreativeGenerationSpec — the provider-independent, structured statement
of *what visual is being generated, for what website role, and how each
reference may be used* (P2.2). It sits between a CreativeBrief (verified
business facts + brand/level intent) and a provider adapter: no adapter
ever assembles creative strategy from business fields itself — it
translates a spec (via app.domain.creative.prompt_composer) into its own
payload.

Reuses existing vocabulary rather than duplicating it: brand mode is
app.domain.enums.BrandStrategy (PRESERVE/EVOLVE/NEW_DIRECTION) and the
creative level is app.domain.enums.CreativeLevel. Pure domain data: no
FastAPI, SQLAlchemy, network or provider SDKs.

THE REFERENCE ASSET IS NOT THE OUTPUT INTENT: a reference constrains
identity/palette/style/composition; it never means "recreate this
reference". ReferenceUsage makes that explicit per reference.
"""

from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, AssetPurpose, BrandStrategy, CreativeLevel

# Bump whenever composed-prompt wording/structure changes materially, so a
# persisted asset can always be traced to the composition rules that
# produced it.
PROMPT_VERSION = "p2.2-v1"


class ReferenceUsage(StrEnum):
    """WHY a reference is supplied. A logo is IDENTITY and/or PALETTE,
    never SUBJECT."""

    IDENTITY = "identity"
    PALETTE = "palette"
    STYLE = "style"
    SUBJECT = "subject"
    PRODUCT = "product"
    COMPOSITION = "composition"


class TextPolicy(StrEnum):
    """Generated website imagery never bakes in text: business names,
    headings, CTAs and prices are rendered by HTML/CSS. No purpose enables
    generated text today; a future one must add an explicit member here
    rather than silently relaxing this default."""

    NO_GENERATED_TEXT = "no_generated_text"


class ReferenceSpec(BaseModel):
    """One reference and the role it plays. Carries ids/semantics only —
    never a URL: provider adapters resolve `asset_id` to whatever
    location they need (presigned R2 URL, local path), and that resolved
    location is never persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: UUID | None
    usage: ReferenceUsage
    asset_kind: AssetKind | None = None
    asset_category: AssetCategory | None = None
    # "business_asset" for a real BusinessAsset row; "previous_generation"
    # for the earlier generated image a develop step continues from.
    source: str = "business_asset"


class OutputRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aspect_ratio: str
    num_outputs: int = 1
    media_types: tuple[str, ...] = ("png", "jpg", "webp")


class CreativeGenerationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: AssetPurpose
    brand_mode: BrandStrategy
    creative_level: CreativeLevel
    text_policy: TextPolicy = TextPolicy.NO_GENERATED_TEXT
    # Ranked candidates, best first. A provider uses the first ones it can
    # actually resolve, up to its own model limit, then calls
    # `with_used_references` so the composed prompt only ever describes
    # references that were really sent.
    reference_assets: list[ReferenceSpec] = Field(default_factory=list)
    output: OutputRequirements

    def with_used_references(self, used: Sequence[ReferenceSpec]) -> "CreativeGenerationSpec":
        return self.model_copy(update={"reference_assets": list(used)})


# Chosen from the set every registered Higgsfield model supports; a
# provider still checks its own supported set before sending.
_ASPECT_RATIO_BY_PURPOSE: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "16:9",
    AssetPurpose.BACKGROUND: "16:9",
    AssetPurpose.SECTION: "4:3",
    AssetPurpose.PRODUCT: "1:1",
    AssetPurpose.EDITORIAL: "3:2",
    AssetPurpose.TEXTURE: "1:1",
}

_PALETTE_ONLY_PURPOSES = frozenset({AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE})


def _is_logo(asset: CreativeBriefAsset) -> bool:
    return asset.kind is AssetKind.LOGO or asset.category is AssetCategory.LOGO


def reference_usage_for(asset: CreativeBriefAsset, purpose: AssetPurpose, brand_mode: BrandStrategy) -> ReferenceUsage:
    """The single place that decides why an asset is being supplied."""
    if _is_logo(asset):
        if brand_mode is BrandStrategy.NEW_DIRECTION or purpose in _PALETTE_ONLY_PURPOSES:
            return ReferenceUsage.PALETTE
        return ReferenceUsage.IDENTITY
    if asset.category is AssetCategory.PRODUCT:
        return ReferenceUsage.PRODUCT if purpose is AssetPurpose.PRODUCT else ReferenceUsage.STYLE
    if asset.category is AssetCategory.HERO_CANDIDATE and purpose in (AssetPurpose.HERO, AssetPurpose.SECTION):
        return ReferenceUsage.COMPOSITION
    return ReferenceUsage.STYLE


def _rank(asset: CreativeBriefAsset, usage: ReferenceUsage, purpose: AssetPurpose, brand_mode: BrandStrategy) -> int:
    """Lower is better."""
    if purpose is AssetPurpose.PRODUCT:
        order = {
            ReferenceUsage.PRODUCT: 0,
            ReferenceUsage.IDENTITY: 1,
            ReferenceUsage.PALETTE: 1,
            ReferenceUsage.COMPOSITION: 2,
            ReferenceUsage.STYLE: 3,
        }
    elif brand_mode is BrandStrategy.NEW_DIRECTION:
        # References may inform context but must not constrain a genuinely
        # new direction: palette cues first, real photography only as style.
        order = {
            ReferenceUsage.PALETTE: 0,
            ReferenceUsage.STYLE: 1,
            ReferenceUsage.COMPOSITION: 2,
            ReferenceUsage.PRODUCT: 3,
            ReferenceUsage.IDENTITY: 3,
        }
    else:
        order = {
            ReferenceUsage.IDENTITY: 0,
            ReferenceUsage.PALETTE: 0,
            ReferenceUsage.COMPOSITION: 1,
            ReferenceUsage.PRODUCT: 2,
            ReferenceUsage.STYLE: 2,
        }
    origin_penalty = 10 if asset.origin is AssetOrigin.GENERATED else 0
    return order[usage] + origin_penalty


def select_references(
    assets: Sequence[CreativeBriefAsset],
    *,
    purpose: AssetPurpose,
    brand_mode: BrandStrategy,
    limit: int,
) -> list[ReferenceSpec]:
    """Ranked reference candidates for a purpose. Only image-bearing
    assets qualify (a video/document URL is not a usable image
    reference), and LOW_QUALITY assets are excluded unless they are the
    logo (the real brand mark is always authoritative). `assets` must
    already be tenant/business-scoped and availability-filtered — see
    build_creative_brief — this function never widens that set. The sort
    is stable, so among equally ranked assets the caller's own order
    (newest first) is preserved."""
    candidates: list[tuple[int, int, CreativeBriefAsset, ReferenceUsage]] = []
    for position, asset in enumerate(assets):
        if asset.kind not in (AssetKind.LOGO, AssetKind.IMAGE):
            continue
        if asset.category is AssetCategory.LOW_QUALITY and not _is_logo(asset):
            continue
        usage = reference_usage_for(asset, purpose, brand_mode)
        candidates.append((_rank(asset, usage, purpose, brand_mode), position, asset, usage))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [
        ReferenceSpec(asset_id=asset.id, usage=usage, asset_kind=asset.kind, asset_category=asset.category)
        for _, _, asset, usage in candidates[: max(limit, 0)]
    ]


def build_generation_spec(
    brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], *, max_reference_candidates: int = 3
) -> CreativeGenerationSpec:
    """Deterministic: brief (facts + brand mode + level + purpose) plus
    the business's own available assets in, structured spec out."""
    return CreativeGenerationSpec(
        purpose=brief.asset_purpose,
        brand_mode=brief.brand_strategy,
        creative_level=brief.creative_level,
        reference_assets=select_references(
            assets, purpose=brief.asset_purpose, brand_mode=brief.brand_strategy, limit=max_reference_candidates
        ),
        output=OutputRequirements(aspect_ratio=_ASPECT_RATIO_BY_PURPOSE[brief.asset_purpose]),
    )
