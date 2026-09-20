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
from app.domain.creative.generation_contract import GenerationContract, build_generation_contract
from app.domain.creative.model_routing import CreativeGenerationRequirements
from app.domain.creative.reference_strategy import ReferencePolicy, ReferenceStrategy, decide_reference_strategy
from app.domain.creative.scene_plan import VisualScenePlan, plan_scenes
from app.domain.creative.spec import CreativeGenerationSpec, ReferenceSpec, build_generation_spec
from app.domain.creative.visual_intent import VisualIntent, resolve_visual_intent
from app.domain.creative.visual_subject import VisualSubject, select_visual_subject


class GenerationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: CreativeGenerationSpec
    profile: BrandVisualProfile
    # P2.4: only the visually relevant, verified business knowledge, and what
    # the image should depict (separate from where it will be used).
    context: CreativeContext
    intent: VisualIntent
    # P2.5: the ONE narrow subject, the concrete scene variants that depict it,
    # and the provider-independent contract validated before any spend.
    subject: VisualSubject
    scenes: tuple[VisualScenePlan, ...]
    contract: GenerationContract
    strategy: ReferenceStrategy
    requirements: CreativeGenerationRequirements

    def contract_for(self, variant: int, references: Sequence[ReferenceSpec] | None = None) -> GenerationContract:
        """The contract for exploration `variant` (a different, deterministic
        scene of the same subject), optionally with the references that were
        actually selected for the provider."""
        contract = self.contract.with_scene(self.scenes[variant % len(self.scenes)])
        return contract if references is None else contract.with_provider_references(references)


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
    subject = select_visual_subject(intent=intent, context=context)
    scenes = plan_scenes(
        purpose=spec.purpose,
        intent=intent,
        subject=subject,
        profile=profile,
        brand_mode=spec.brand_mode,
        creative_level=spec.creative_level,
        aspect_ratio=spec.output.aspect_ratio,
    )
    contract = build_generation_contract(spec=spec, intent=intent, subject=subject, scene=scenes[0], strategy=strategy)
    return GenerationPlan(
        spec=spec,
        profile=profile,
        context=context,
        intent=intent,
        subject=subject,
        scenes=scenes,
        contract=contract,
        strategy=strategy,
        requirements=requirements_for(spec, strategy),
    )
