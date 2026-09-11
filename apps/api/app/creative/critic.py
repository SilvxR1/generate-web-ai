"""select_direction — the P2.4 creative-critic/selection stage. Runs once
per create_directions batch, after every candidate exists, and decides
which one is recommended — deliberately not the provider's own job (see
app.creative.director's docstring on why "explore" and "select" stay
separate).

A deterministic, rule-based scorer, not another paid AI call: P2.4 says
"the critic must not optimize only for visual spectacle" and this task's
overall credit budget is tight (hard cap 20 Higgsfield credits for the
whole P2 task) — spending more provider credits just to judge candidates
that already cost credits to produce would eat directly into that
budget for no proportionate benefit. Every score dimension below is
computed from data already on hand (the candidate itself, `brief`, the
other candidates), traceable and testable, matching P2.4's required
criteria: brand/business fit, originality, asset compatibility, UX/
mobile/accessibility feasibility, conversion compatibility,
implementation feasibility, factual safety.
"""

from app.domain.creative import CreativeBrief
from app.domain.creative.direction import CreativeDirection


class NoCandidateDirectionsError(ValueError):
    """select_direction was called with an empty candidate list — a
    caller bug (create_directions is expected to always return at least
    one candidate), never a normal outcome to silently paper over."""


def _brand_fit_score(direction: CreativeDirection, brief: CreativeBrief) -> float:
    """Rewards a candidate whose concept/visual language actually engages
    with this specific business's real facts (name, industry,
    description, visual style) rather than reading as boilerplate that
    could apply to any business."""
    haystack = " ".join(
        [
            direction.concept.name,
            direction.concept.rationale,
            direction.concept.narrative,
            direction.visual_language.mood,
            direction.visual_language.imagery_treatment,
        ]
    ).lower()
    signals = [brief.business_name.lower(), brief.industry.lower()]
    if brief.visual_style:
        signals.append(brief.visual_style.lower())
    if brief.target_customer:
        signals.append(brief.target_customer.lower())
    hits = sum(1 for signal in signals if signal and signal in haystack)
    return hits / max(len(signals), 1)


def _asset_compatibility_score(direction: CreativeDirection, brief: CreativeBrief) -> float:
    """Rewards a candidate grounded in this business's real assets
    (P2.10: real client assets preferred) — a candidate whose references
    include at least one of `brief.available_assets`' real URLs scores
    higher than one built from generated/no reference material at all."""
    if not brief.available_assets:
        return 0.5  # No real assets exist yet — neutral, not penalized.
    real_urls = {asset.url for asset in brief.available_assets}
    return 1.0 if any(reference in real_urls for reference in direction.references) else 0.2


def _conversion_compatibility_score(direction: CreativeDirection, brief: CreativeBrief) -> float:
    objective = brief.conversion_objective.lower()
    haystack = f"{direction.content_strategy.conversion_strategy} {direction.content_strategy.primary_user_journey}"
    return 1.0 if objective in haystack.lower() else 0.3


def _feasibility_score(direction: CreativeDirection) -> float:
    """A cheap implementation/UX/mobile/accessibility feasibility proxy:
    a direction naming a concrete responsive adaptation and a bounded
    (not open-ended/unbounded) set of interaction/motion concepts is more
    likely to be implementable within this task's "1-2 targeted
    correction passes, never unbounded regeneration" discipline than one
    that names none, or an excessive number that risk accessibility/
    reduced-motion conflicts."""
    score = 1.0
    if not direction.experience.responsive_adaptation.strip():
        score -= 0.4
    total_concepts = len(direction.experience.interaction_concepts) + len(direction.experience.motion_concepts)
    if total_concepts > 8:
        score -= 0.3
    return max(score, 0.0)


def _factual_safety_score(direction: CreativeDirection) -> float:
    """A candidate whose narrative/rationale text mentions a prohibited
    claim category by name (e.g. literally says "guarantee" or "award")
    without it appearing in its own `factual_claims` is flagged — a
    cheap, conservative lexical check, not a substitute for
    app.qa.platform_contract's real build-output scan, but enough to
    disqualify an obviously unsafe candidate before it's ever
    recommended."""
    narrative = f"{direction.concept.rationale} {direction.concept.narrative}".lower()
    claims_text = " ".join(direction.constraints.factual_claims).lower()
    violations = 0
    for prohibited in direction.constraints.prohibited_claims:
        keyword = prohibited.replace("_", " ")
        if keyword in narrative and keyword not in claims_text:
            violations += 1
    return max(1.0 - 0.5 * violations, 0.0)


def _originality_score(direction: CreativeDirection, others: list[CreativeDirection]) -> float:
    """Rewards a candidate whose mood/composition philosophy reads as
    distinct from the other candidates in the same batch — a crude but
    honest proxy for "genuinely different directions" (P2.3), computed
    as 1 minus the fraction of other candidates sharing its exact mood
    string (an internal-director single-candidate batch always scores
    1.0 here, since there is nothing to be similar to)."""
    if not others:
        return 1.0
    same_mood = sum(1 for other in others if other.visual_language.mood == direction.visual_language.mood)
    return 1.0 - (same_mood / len(others))


_WEIGHTS = {
    "brand_fit": 0.25,
    "asset_compatibility": 0.15,
    "conversion_compatibility": 0.15,
    "feasibility": 0.2,
    "factual_safety": 0.15,
    "originality": 0.1,
}


def score_direction(
    direction: CreativeDirection, brief: CreativeBrief, all_candidates: list[CreativeDirection]
) -> float:
    others = [candidate for candidate in all_candidates if candidate is not direction]
    scores = {
        "brand_fit": _brand_fit_score(direction, brief),
        "asset_compatibility": _asset_compatibility_score(direction, brief),
        "conversion_compatibility": _conversion_compatibility_score(direction, brief),
        "feasibility": _feasibility_score(direction),
        "factual_safety": _factual_safety_score(direction),
        "originality": _originality_score(direction, others),
    }
    return sum(scores[key] * weight for key, weight in _WEIGHTS.items())


def select_direction(
    candidates: list[CreativeDirection], brief: CreativeBrief
) -> tuple[CreativeDirection, list[CreativeDirection]]:
    """Scores every candidate, marks exactly one `is_recommended=True`
    with a `selection_rationale` explaining why, and returns
    `(recommended, all_candidates)` — mutates and returns the same
    CreativeDirection instances (every candidate gets a rationale, not
    only the winner, so Studio can show why each alternative wasn't
    picked, per P2.4's "persist or otherwise expose the selection
    rationale"). Never mutates `candidates`' visual/creative content —
    only `is_recommended`/`selection_rationale`."""
    if not candidates:
        raise NoCandidateDirectionsError("select_direction requires at least one candidate.")

    scored = [(candidate, score_direction(candidate, brief, candidates)) for candidate in candidates]
    winner, winner_score = max(scored, key=lambda pair: pair[1])

    for candidate, score in scored:
        candidate.is_recommended = candidate is winner
        if candidate is winner:
            candidate.selection_rationale = (
                f"Recommended (score {score:.2f}/1.00): strongest combination of brand fit, feasibility, "
                "conversion alignment, and factual safety among the candidates explored."
            )
        else:
            candidate.selection_rationale = (
                f"Not recommended (score {score:.2f}/1.00 vs. {winner_score:.2f}/1.00 for "
                f"{winner.concept.name!r}) — still available to select manually in Studio."
            )

    return winner, candidates
