"""Generated image QA service (P2.7) — the lifecycle glue.

Where it runs (app.creative.director_orchestrator.orchestrate_create_directions):

    provider completes → candidate has a result URL + recorded provenance
        → THIS: fetch bytes (bounded) → technical + visual checks
        → result written to provenance (`creative_spec["visual_qa"]`)
        → select_direction (a blocked candidate cannot be recommended)
        → human selection (a blocked candidate cannot become a website draft)

It is deliberately outside every provider adapter: the Higgsfield director knows
nothing about brand, composition or QA, so any future provider gets the same QA
for free. It reads only what the generation already recorded (result URL,
scene_plan, purpose) — no access to the live contract or to any secret.

FAILURE SEMANTICS. The provider job stays `completed` whatever QA finds:
  * QA rejects the image  → `visual_qa.approval_eligible = false` (blocking checks only);
  * QA cannot get the artifact / is over its limits / errors → every check is
    NOT_PERFORMED. That is a visible coverage gap, never a pass and never a block:
    an infrastructure problem must not reject a good candidate.
"""

import logging
from collections.abc import Mapping

from app.creative.artifact_fetcher import ArtifactFetcher, ArtifactFetchError
from app.domain.creative.direction import CreativeDirection
from app.domain.creative.image_qa import (
    ImageQAResult,
    SemanticAnalyzer,
    requirements_from_provenance,
    run_image_qa,
    unavailable_result,
)
from app.domain.creative.image_qa.models import CheckStatus

logger = logging.getLogger(__name__)


class GeneratedImageQAService:
    def __init__(self, fetcher: ArtifactFetcher, *, analyzers: Mapping[str, SemanticAnalyzer] | None = None) -> None:
        self._fetcher = fetcher
        self._analyzers = analyzers or {}

    def evaluate(self, candidate: CreativeDirection) -> ImageQAResult | None:
        """None when the candidate has no generated image (e.g. an internal
        fallback direction): there is nothing to inspect and nothing is claimed."""
        spec = candidate.generation_metadata.get("creative_spec")
        if not isinstance(spec, dict) or spec.get("generated_image") is False or not candidate.references:
            return None
        requirements = requirements_from_provenance(spec)
        try:
            data = self._fetcher.fetch(candidate.references[0])
        except ArtifactFetchError as exc:
            reason = "analysis_limits_exceeded" if exc.code == "too_large" else "artifact_unavailable"
            return unavailable_result(requirements, reason=reason, detail=exc.code)
        return run_image_qa(data, requirements, analyzers=self._analyzers)


def attach_image_qa(candidate: CreativeDirection, service: GeneratedImageQAService) -> None:
    """Run QA for one candidate and record it in its provenance. Never raises:
    Visual QA is not allowed to break generation."""
    spec = candidate.generation_metadata.get("creative_spec")
    if not isinstance(spec, dict):
        return
    try:
        result = service.evaluate(candidate)
    except Exception:  # noqa: BLE001 — QA must never break a completed generation
        logger.warning("image_qa_unexpected_failure")
        result = unavailable_result(requirements_from_provenance(spec), reason="qa_error")
    if result is None:
        return
    spec["visual_qa"] = result.model_dump(mode="json")
    # The metadata validator's static "visual_qa: not_performed" / "not_covered"
    # must now say what is actually true.
    validation = spec.get("validation")
    if isinstance(validation, dict):
        ran = result.overall_status is not CheckStatus.NOT_PERFORMED
        validation["visual_qa"] = "performed" if ran else "not_performed"
        validation["not_covered"] = list(result.coverage.not_performed)
    logger.info(
        "image_qa_completed status=%s approval_eligible=%s", result.overall_status.value, result.approval_eligible
    )
