"""InternalCreativeDirector — the free, always-available
CreativeDirectorProvider implementation (mirrors
app.creative.internal.InternalCreativeProvider's role: fallback
capability, provider-outage fallback, a working non-Higgsfield
development/test path — never a second, competing source of creative
exploration).

Honest about its own limits: it has no image-generation or moodboard
capability of any kind, so it can't produce several genuinely different
*visual* directions the way HiggsfieldCreativeDirector
(app.creative.higgsfield.director) can — it returns exactly one
CreativeDirection, built entirely from `brief`'s own already-known facts
(the same "no invention" discipline
app.creative.internal.InternalCreativeProvider.generate_concept already
follows), spends zero credits, and marks that single candidate
recommended by construction (there is nothing to compare it against).
`develop_direction` is a no-op that returns `selected` unchanged plus a
`generation_metadata` note explaining why — never a fabricated "deepened"
result.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.creative.director import CreativeDirectorProvider
from app.creative.factual_safety import constraints_for_brief
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import CreativeProviderName


class InternalCreativeDirector(CreativeDirectorProvider):
    name = CreativeProviderName.INTERNAL

    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        del budget  # No spend: the internal director makes no provider calls.
        direction = CreativeDirection(
            concept=CreativeConcept(
                name=f"{brief.business_name} — existing brand direction",
                rationale=(
                    "No premium creative provider is configured or selected: this direction reflects "
                    f"{brief.business_name}'s own already-known brand facts (industry: {brief.industry}, "
                    f"strategy: {brief.brand_strategy.value}) rather than an AI-explored concept."
                ),
                narrative=brief.description or f"{brief.business_name} — {brief.industry}",
            ),
            visual_language=VisualLanguage(
                mood="derived from the business's existing brand configuration, not independently explored",
                palette_direction=brief.brand_colors.model_dump_json() if brief.brand_colors else "not yet set",
                typography_direction=brief.typography.model_dump_json() if brief.typography else "not yet set",
                composition_philosophy="deterministic block composition (packages/website-generator)",
                imagery_treatment=brief.visual_style or "real business photography, unaltered",
                graphic_language="no generated graphic language — real assets only",
            ),
            experience=ExperienceDirection(
                navigation_concept="single-page section scroll (deterministic engine default)",
                storytelling_model="hero -> services -> proof -> contact",
                interaction_concepts=[],
                motion_concepts=[],
                responsive_adaptation="deterministic engine's existing responsive block layout",
            ),
            content_strategy=ContentStrategy(
                hierarchy="; ".join(brief.required_sections) or "hero; cta",
                primary_user_journey=f"arrival -> {brief.conversion_objective}",
                conversion_strategy=brief.conversion_objective,
            ),
            references=[],
            constraints=constraints_for_brief(brief),
            provider_metadata={"provider": self.name.value, "strategy": "existing_brand_and_theme"},
            generation_metadata={"credits_used": 0.0, "stage": "initial_direction", "candidate_count": 1},
            is_recommended=True,
            selection_rationale=(
                "Only candidate: InternalCreativeDirector has no exploratory capability, so nothing to "
                "compare it against."
            ),
        )
        return [direction]

    def develop_direction(
        self,
        selected: CreativeDirection,
        brief: CreativeBrief,
        assets: Sequence[CreativeBriefAsset],
        budget: CreativeBudget,
    ) -> CreativeDirection:
        del brief, assets, budget
        developed = selected.model_copy(deep=True)
        developed.generation_metadata = {
            **developed.generation_metadata,
            "stage": "developed",
            "note": "InternalCreativeDirector cannot deepen a direction (no exploratory capability) — unchanged.",
            "developed_at": datetime.now(UTC).isoformat(),
        }
        return developed
