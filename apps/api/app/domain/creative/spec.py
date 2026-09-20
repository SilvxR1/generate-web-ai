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
what it is *for* (style, subject, product, composition); it never means
"recreate this reference". P2.3 goes one step further — whether an asset
is sent to a generation model at all is decided by
app.domain.creative.reference_strategy, not here. `reference_assets` on a
spec are only the references actually intended for the provider.
"""

from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brief import CreativeBrief
from app.domain.enums import AssetCategory, AssetKind, AssetPurpose, BrandStrategy, CreativeLevel

# Bump whenever composed-prompt wording/structure changes materially, so a
# persisted asset can always be traced to the composition rules that
# produced it.
PROMPT_VERSION = "p2.3-v1"


class ReferenceUsage(StrEnum):
    """WHY a reference is supplied. IDENTITY and PALETTE describe brand
    sources (an official logo); since P2.3 those inform the
    BrandVisualProfile and are not sent to a generation model."""

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
    # References intended for the provider, best first. Empty is the
    # normal case for HERO/BACKGROUND/TEXTURE. A provider uses the first
    # ones it can actually resolve, up to its model's limit, then calls
    # `with_used_references` so the composed prompt only ever describes
    # references that were really sent.
    reference_assets: list[ReferenceSpec] = Field(default_factory=list)
    output: OutputRequirements

    def with_used_references(self, used: Sequence[ReferenceSpec]) -> "CreativeGenerationSpec":
        return self.model_copy(update={"reference_assets": list(used)})


# Chosen from the set every registered Higgsfield model supports; the
# model router still checks each model's own supported set.
_ASPECT_RATIO_BY_PURPOSE: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "16:9",
    AssetPurpose.BACKGROUND: "16:9",
    AssetPurpose.SECTION: "4:3",
    AssetPurpose.PRODUCT: "1:1",
    AssetPurpose.EDITORIAL: "3:2",
    AssetPurpose.TEXTURE: "1:1",
}


def aspect_ratio_for_purpose(purpose: AssetPurpose) -> str:
    return _ASPECT_RATIO_BY_PURPOSE[purpose]


def build_generation_spec(
    brief: CreativeBrief, reference_assets: Sequence[ReferenceSpec] = ()
) -> CreativeGenerationSpec:
    """Deterministic: the brief's purpose/brand mode/level plus whichever
    references the reference strategy decided may go to a provider."""
    return CreativeGenerationSpec(
        purpose=brief.asset_purpose,
        brand_mode=brief.brand_strategy,
        creative_level=brief.creative_level,
        reference_assets=list(reference_assets),
        output=OutputRequirements(aspect_ratio=aspect_ratio_for_purpose(brief.asset_purpose)),
    )
