"""CreativeDirection / CreativeBudget / InternalCreativeDirector /
select_direction (app.creative.director, app.creative.director_internal,
app.creative.critic, app.domain.creative.budget) — domain, budget-
enforcement, and selection/critic tests per P2's testing requirements."""

import pytest

from app.creative.critic import NoCandidateDirectionsError, select_direction
from app.creative.director_internal import InternalCreativeDirector
from app.creative.errors import CreativeProviderError
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.brief import build_creative_brief
from app.domain.creative.budget import BudgetExceededError, CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import BusinessVertical, CreativeBudgetTier


def _profile(**overrides: object) -> BusinessProfile:
    data = {"name": "Cositas y Puntos", "slug": "cositas-y-puntos", "industry": BusinessVertical.OTHER}
    data.update(overrides)
    return BusinessProfile(**data)


def _brief(**overrides: object):
    config = BusinessConfig(
        business_profile=_profile(
            description="Amigurumi y crochet hechos a mano.", target_customers="regalos personalizados"
        ),
    )
    return build_creative_brief(business_config=config)


def _direction(**overrides: object) -> CreativeDirection:
    fields = dict(
        concept=CreativeConcept(name="Handmade warmth", rationale="Cositas y Puntos handmade crochet", narrative="n"),
        visual_language=VisualLanguage(
            mood="warm handmade",
            palette_direction="terracotta",
            typography_direction="hand-drawn",
            composition_philosophy="asymmetric",
            imagery_treatment="real photos",
            graphic_language="hand-drawn icons",
        ),
        experience=ExperienceDirection(
            navigation_concept="scroll",
            storytelling_model="linear",
            interaction_concepts=["hover tilt"],
            motion_concepts=["fade in"],
            responsive_adaptation="stacked cards on mobile",
        ),
        content_strategy=ContentStrategy(
            hierarchy="hero; products; contact",
            primary_user_journey="browse -> contact",
            conversion_strategy="lead_capture",
        ),
    )
    fields.update(overrides)
    return CreativeDirection(**fields)


# --- CreativeBudget ---------------------------------------------------


def test_budget_for_tier_uses_documented_defaults():
    standard = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    assert standard.hard_limit == 20.0
    assert standard.target_min == 10.0 and standard.target_max == 15.0

    premium = CreativeBudget.for_tier(CreativeBudgetTier.PREMIUM)
    assert premium.hard_limit == 50.0


def test_budget_experimental_tier_requires_explicit_hard_limit():
    with pytest.raises(ValueError):
        CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL)

    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=7.0)
    assert budget.hard_limit == 7.0


def test_budget_record_spend_accumulates_and_tracks_calls():
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    budget.record_spend(2.0, provider="higgsfield", operation="create_directions", model="nano_banana_pro", iteration=1)
    budget.record_spend(2.0, provider="higgsfield", operation="create_directions", model="nano_banana_pro", iteration=2)

    assert budget.credits_used == 4.0
    assert len(budget.calls) == 2
    assert budget.remaining() == 16.0


def test_budget_record_spend_refuses_before_exceeding_hard_limit():
    budget = CreativeBudget.for_tier(CreativeBudgetTier.EXPERIMENTAL, hard_limit=3.0)
    budget.record_spend(2.0, provider="higgsfield", operation="create_directions")

    with pytest.raises(BudgetExceededError):
        budget.record_spend(2.0, provider="higgsfield", operation="create_directions")

    # The refused call never happened — credits_used/calls unchanged.
    assert budget.credits_used == 2.0
    assert len(budget.calls) == 1


def test_budget_exceeded_error_is_a_creative_provider_error():
    assert issubclass(BudgetExceededError, CreativeProviderError)


# --- InternalCreativeDirector ------------------------------------------


def test_internal_director_returns_one_honest_candidate_with_no_spend():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)

    candidates = InternalCreativeDirector().create_directions(brief, [], budget)

    assert len(candidates) == 1
    assert candidates[0].is_recommended is True
    assert budget.credits_used == 0.0
    assert "Cositas y Puntos" in candidates[0].concept.rationale


def test_internal_director_never_fabricates_prohibited_claims_as_facts():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    [direction] = InternalCreativeDirector().create_directions(brief, [], budget)

    for prohibited in ("pricing", "years_of_experience", "certifications", "guarantees", "awards"):
        assert prohibited in direction.constraints.prohibited_claims
    # Every factual claim traces back to real brief fields, never a
    # fabricated one of the prohibited categories.
    assert all("guarantee" not in claim.lower() for claim in direction.constraints.factual_claims)


def test_internal_director_develop_direction_is_an_honest_no_op():
    brief = _brief()
    budget = CreativeBudget.for_tier(CreativeBudgetTier.STANDARD)
    director = InternalCreativeDirector()
    [selected] = director.create_directions(brief, [], budget)

    developed = director.develop_direction(selected, brief, [], budget)

    assert developed.concept.name == selected.concept.name
    assert developed.generation_metadata["stage"] == "developed"
    assert "cannot deepen" in developed.generation_metadata["note"]
    assert budget.credits_used == 0.0


# --- select_direction critic --------------------------------------------


def test_select_direction_requires_at_least_one_candidate():
    with pytest.raises(NoCandidateDirectionsError):
        select_direction([], _brief())


def test_select_direction_picks_the_most_business_relevant_candidate():
    brief = _brief()
    on_brand = _direction(
        concept=CreativeConcept(
            name="Cositas y Puntos handmade world",
            rationale="Grounded in Cositas y Puntos' handmade, artisanal crochet identity",
            narrative="A warm, handmade world for Cositas y Puntos",
        )
    )
    generic = _direction(
        concept=CreativeConcept(name="Modern Minimal", rationale="A generic modern minimal concept", narrative="n"),
        visual_language=VisualLanguage(
            mood="cold corporate minimal",
            palette_direction="grayscale",
            typography_direction="geometric sans",
            composition_philosophy="grid",
            imagery_treatment="stock photography",
            graphic_language="none",
        ),
    )

    winner, all_candidates = select_direction([generic, on_brand], brief)

    assert winner is on_brand
    assert on_brand.is_recommended is True
    assert generic.is_recommended is False
    assert winner.selection_rationale and "Recommended" in winner.selection_rationale
    assert generic.selection_rationale and "Not recommended" in generic.selection_rationale
    assert all_candidates == [generic, on_brand]


def test_select_direction_single_candidate_batch_is_always_recommended():
    brief = _brief()
    only = _direction()

    winner, _ = select_direction([only], brief)

    assert winner is only
    assert only.is_recommended is True


def test_select_direction_penalizes_unsafe_narrative_language():
    brief = _brief()
    safe = _direction()
    unsafe = _direction(
        concept=CreativeConcept(
            name="Award winning guaranteed",
            rationale="This business has won several awards and offers a guarantee on every order",
            narrative="award winning guarantee",
        )
    )

    winner, _ = select_direction([safe, unsafe], brief)

    assert winner is safe
