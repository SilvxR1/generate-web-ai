"""GenerationPlan (P2.3) — the provider-independent decision record for one
generation: what to generate (spec), what identity information to convey
(BrandVisualProfile), which assets may go to a provider (reference
strategy) and what a model must be capable of (requirements).

Both provider adapters and the InternalCreativeDirector consume the same
plan, so the intent is identical whichever provider ends up running it.
Model *selection* is deliberately not part of the plan: it depends on the
provider's registered models and happens in the adapter via
app.domain.creative.model_routing.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.creative.brand_profile import BrandVisualProfile, build_brand_visual_profile
from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.creative.creative_context import CreativeContext, build_creative_context
from app.domain.creative.model_routing import CreativeGenerationRequirements
from app.domain.creative.reference_strategy import ReferencePolicy, ReferenceStrategy, decide_reference_strategy
from app.domain.creative.spec import CreativeGenerationSpec, build_generation_spec
from app.domain.creative.visual_intent import VisualIntent, resolve_visual_intent


class GenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: CreativeGenerationSpec
    profile: BrandVisualProfile
    # P2.4: only the visually relevant, verified business knowledge, and what
    # the image should depict (separate from where it will be used).
    context: CreativeContext
    intent: VisualIntent
    strategy: ReferenceStrategy
    requirements: CreativeGenerationRequirements


def requirements_for(spec: CreativeGenerationSpec, strategy: ReferenceStrategy) -> CreativeGenerationRequirements:
    candidates = len(strategy.provider_reference_candidates)
    return CreativeGenerationRequirements(
        aspect_ratio=spec.output.aspect_ratio,
        text_policy=spec.text_policy,
        requires_visual_reference=strategy.requires_visual_reference,
        required_reference_count=1 if strategy.requires_visual_reference else 0,
        optional_reference_count=candidates if strategy.policy is ReferencePolicy.OPTIONAL_STYLE_REFERENCE else 0,
    )


def plan_generation(
    brief: CreativeBrief,
    assets: Sequence[CreativeBriefAsset],
    *,
    asset_palettes: Mapping[UUID, Sequence[str]] | None = None,
) -> GenerationPlan:
    """`assets` must already be tenant/business-scoped and
    availability-filtered (build_creative_brief's `available_assets`); the
    plan never widens that set."""
    profile = build_brand_visual_profile(brief, assets, asset_palettes=asset_palettes)
    strategy = decide_reference_strategy(brief, assets)
    spec = build_generation_spec(brief, strategy.provider_reference_candidates)
    context = build_creative_context(brief)
    intent = resolve_visual_intent(
        purpose=brief.asset_purpose,
        brand_mode=brief.brand_strategy,
        context=context,
        profile=profile,
        assets=assets,
    )
    return GenerationPlan(
        spec=spec,
        profile=profile,
        context=context,
        intent=intent,
        strategy=strategy,
        requirements=requirements_for(spec, strategy),
    )
