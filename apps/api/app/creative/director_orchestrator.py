"""director_orchestrator — the P2 counterpart to
app.creative.orchestrator.orchestrate_generation, but for the
CreativeDirectorProvider workflow (create_directions -> critic ->
develop_direction) rather than a single CreativeProvider call. Persists
every candidate as a CreativeDirection row (app.db.models.creative_direction),
runs the deterministic critic (app.creative.critic) once all candidates
exist, and — on request — deepens the selected one. Contains no
vendor-specific logic, same "orchestrator never knows which provider
it's calling" discipline as app.creative.orchestrator's own docstring.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.creative.critic import select_direction
from app.creative.director import CreativeDirectorProvider
from app.db.models.creative_direction import CreativeDirection as CreativeDirectionRow
from app.db.models.creative_generation import CreativeGeneration
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    CreativeDirectionConstraints,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import CreativeGenerationStatus, CreativeGenerationType, CreativeLevel
from app.repositories.creative_direction import CreativeDirectionRepository
from app.repositories.creative_generation import CreativeGenerationRepository


class CreativeDirectionNotFoundError(ValueError):
    """No CreativeDirection row matches the given id/business/tenant —
    the caller (a router) maps this to a 404."""


def domain_from_row(row: CreativeDirectionRow) -> CreativeDirection:
    return CreativeDirection(
        concept=CreativeConcept(**row.concept),
        visual_language=VisualLanguage(**row.visual_language),
        experience=ExperienceDirection(**row.experience),
        content_strategy=ContentStrategy(**row.content_strategy),
        references=list(row.references_),
        constraints=CreativeDirectionConstraints(**row.constraints),
        provider_metadata=dict(row.provider_metadata),
        generation_metadata=dict(row.generation_metadata),
        is_recommended=row.is_recommended,
        selection_rationale=row.selection_rationale,
    )


def _apply_domain_to_row(direction: CreativeDirection, row: CreativeDirectionRow) -> None:
    row.concept = direction.concept.model_dump(mode="json")
    row.visual_language = direction.visual_language.model_dump(mode="json")
    row.experience = direction.experience.model_dump(mode="json")
    row.content_strategy = direction.content_strategy.model_dump(mode="json")
    row.references_ = list(direction.references)
    row.constraints = direction.constraints.model_dump(mode="json")
    row.provider_metadata = dict(direction.provider_metadata)
    row.generation_metadata = dict(direction.generation_metadata)
    row.is_recommended = direction.is_recommended
    row.selection_rationale = direction.selection_rationale
    credits = direction.generation_metadata.get("credits_used")
    if isinstance(credits, int | float):
        row.credits_used = float(credits)


def orchestrate_create_directions(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    brief: CreativeBrief,
    assets: Sequence[CreativeBriefAsset],
    director: CreativeDirectorProvider,
    budget: CreativeBudget,
) -> list[CreativeDirectionRow]:
    """STEP A+B+C of P2.3: explore candidates, run the critic, persist
    every candidate (recommended and not) as its own row — mirrors
    app.creative.orchestrator.orchestrate_generation's "persist a
    CreativeGeneration row regardless of outcome" discipline, tracked
    under CreativeGenerationType.CREATIVE_DIRECTION."""
    generation = CreativeGeneration(
        tenant_id=tenant_id,
        business_id=business_id,
        provider=director.name,
        generation_type=CreativeGenerationType.CREATIVE_DIRECTION,
        creative_level=CreativeLevel.PREMIUM,
        status=CreativeGenerationStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    CreativeGenerationRepository(session).add(generation)

    try:
        candidates = director.create_directions(brief, assets, budget)
    except Exception as exc:
        generation.status = CreativeGenerationStatus.FAILED
        generation.error = str(exc)
        generation.completed_at = datetime.now(UTC)
        generation.credits_used = budget.credits_used
        raise

    select_direction(candidates, brief)  # mutates is_recommended/selection_rationale in place

    rows: list[CreativeDirectionRow] = []
    repo = CreativeDirectionRepository(session)
    for candidate in candidates:
        row = CreativeDirectionRow(
            tenant_id=tenant_id,
            business_id=business_id,
            creative_generation_id=generation.id,
            concept={},
            visual_language={},
            experience={},
            content_strategy={},
            references_=[],
            constraints={},
        )
        _apply_domain_to_row(candidate, row)
        rows.append(repo.add(row))

    generation.status = CreativeGenerationStatus.COMPLETED
    generation.completed_at = datetime.now(UTC)
    generation.credits_used = budget.credits_used
    return rows


def orchestrate_develop_direction(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    direction_id: UUID,
    brief: CreativeBrief,
    assets: Sequence[CreativeBriefAsset],
    director: CreativeDirectorProvider,
    budget: CreativeBudget,
) -> CreativeDirectionRow:
    """STEP D of P2.3: deepen one already-selected direction. Never
    creates a new CreativeDirection row — updates the same one in place,
    since it's still the same direction, only richer (see
    CreativeDirectorProvider.develop_direction's own docstring)."""
    repo = CreativeDirectionRepository(session)
    row = repo.get_for_business(tenant_id, business_id, direction_id)
    if row is None:
        raise CreativeDirectionNotFoundError(f"CreativeDirection {direction_id} not found for this business.")

    selected = domain_from_row(row)
    developed = director.develop_direction(selected, brief, assets, budget)
    _apply_domain_to_row(developed, row)
    row.developed_at = datetime.now(UTC)
    return row
