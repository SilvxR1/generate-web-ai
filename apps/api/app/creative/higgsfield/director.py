"""HiggsfieldCreativeDirector — the real Higgsfield-backed
CreativeDirectorProvider (P2.2/P2.3), built on the authenticated
`higgsfield` CLI session (app.creative.higgsfield.cli.HiggsfieldCli), per
the explicit product decision to use the CLI/OAuth-session integration
path rather than a server-held API key (see
docs/higgsfield-integration.md's "CLI integration status" section).

Workflow (P2.3):
  STEP A: create_directions — three distinct prompt explorations, each
    grounded in real CreativeBrief facts (never generic), each costed via
    HiggsfieldCli.estimate_cost *before* the real HiggsfieldCli.create
    call it pays for, recorded on the caller's CreativeBudget.
  STEP D: develop_direction — three further explorations anchored to the
    *same* generated image (passed back as an `--image-references` job
    id, not re-uploaded) once a direction is selected, deepening detail/
    composition rather than starting a new concept.

Never asks Higgsfield to choose one of this platform's own preexisting
design families/templates — every prompt is built from `brief`'s real
facts plus an explicit instruction to propose a genuinely different
composition/interaction/visual-metaphor concept, and the resulting
CreativeDirection's `visual_language`/`experience` fields are populated
from that same prompt text (traceable, never separately invented).
"""

import time
from collections.abc import Sequence
from pathlib import Path

from app.creative.director import CreativeDirectorProvider
from app.creative.factual_safety import constraints_for_brief
from app.creative.higgsfield.cli import HiggsfieldCli, resolve_local_reference
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import AssetKind, CreativeProviderName

DEFAULT_IMAGE_MODEL = "nano_banana_pro"

_EXPLORATION_ANGLES: tuple[str, ...] = (
    "a bespoke visual metaphor drawn directly from the core craft/product itself, treated as the site's "
    "dominant graphic language",
    "a navigation/interaction concept where wayfinding is embedded in the scene itself rather than a "
    "conventional navbar",
    "an editorial, trust-oriented composition built around real photography and hierarchy, for a visitor "
    "who needs to be convinced quickly",
)

_DEVELOP_ANGLES: tuple[str, ...] = (
    "the same exact world and visual language, showing how it adapts to a narrow mobile/portrait viewport",
    "the same exact world and visual language, showing a close, tactile detail/texture shot",
    "the same exact world and visual language, showing the primary conversion moment (contact/CTA) inside it",
)


def _reference_image(assets: Sequence[CreativeBriefAsset], *, local_storage_root: Path | None) -> str | None:
    if local_storage_root is None:
        return None
    preferred = sorted(assets, key=lambda asset: 0 if asset.kind is AssetKind.LOGO else 1)
    for asset in preferred:
        local_path = resolve_local_reference(asset.url, local_storage_root=local_storage_root)
        if local_path:
            return local_path
    return None


def _build_prompt(brief: CreativeBrief, angle: str, *, continuation_of: str | None = None) -> str:
    facts = (
        f"Business: {brief.business_name} ({brief.industry}). "
        + (f"Description: {brief.description}. " if brief.description else "")
        + (f"Target customer: {brief.target_customer}. " if brief.target_customer else "")
        + (f"Visual style so far: {brief.visual_style}. " if brief.visual_style else "")
    )
    if continuation_of:
        return (
            f"Continue this exact world and visual language (do not deviate): {continuation_of}. {facts} "
            f"Now propose: {angle}. No watermark, no browser chrome, no lorem ipsum, high quality."
        )
    return (
        f"{facts} Propose a genuinely bespoke digital creative direction using {angle}. "
        "Do not invent business facts not stated above. No watermark, no browser chrome, no lorem ipsum, "
        "high quality reference image for a website creative-direction exploration."
    )


class HiggsfieldCreativeDirector(CreativeDirectorProvider):
    name = CreativeProviderName.HIGGSFIELD

    def __init__(
        self, cli: HiggsfieldCli, *, image_model: str = DEFAULT_IMAGE_MODEL, local_storage_root: Path | None = None
    ) -> None:
        self._cli = cli
        self._image_model = image_model
        self._local_storage_root = local_storage_root

    def _spend_and_create(
        self, prompt: str, *, reference: str | None, budget: CreativeBudget, operation: str, iteration: int
    ):
        started = time.monotonic()
        credits = self._cli.estimate_cost(self._image_model, prompt=prompt)
        budget.record_spend(
            credits, provider=self.name.value, operation=operation, model=self._image_model, iteration=iteration
        )
        job = self._cli.create(
            self._image_model,
            prompt=prompt,
            image_references=[reference] if reference else None,
            aspect_ratio="16:9",
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return job, credits, duration_ms

    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        reference = _reference_image(assets, local_storage_root=self._local_storage_root)
        candidates: list[CreativeDirection] = []

        for iteration, angle in enumerate(_EXPLORATION_ANGLES, start=1):
            prompt = _build_prompt(brief, angle)
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt, reference=reference, budget=budget, operation="create_directions", iteration=iteration
                )
            except Exception:  # noqa: BLE001 — budget refusal or a real CLI failure both stop exploration here
                budget.record_failure(
                    provider=self.name.value,
                    operation="create_directions",
                    model=self._image_model,
                    iteration=iteration,
                )
                break

            candidates.append(
                CreativeDirection(
                    concept=CreativeConcept(
                        name=f"{brief.business_name} — direction {iteration}",
                        rationale=f"Explored via {angle}.",
                        narrative=prompt,
                    ),
                    visual_language=VisualLanguage(
                        mood=angle,
                        palette_direction="derived from the generated reference image, see references",
                        typography_direction="to be interpreted by the frontend engine from the reference image",
                        composition_philosophy=angle,
                        imagery_treatment="Higgsfield-generated reference image grounding a bespoke visual language",
                        graphic_language=angle,
                    ),
                    experience=ExperienceDirection(
                        navigation_concept=angle if iteration == 2 else "to be interpreted from the reference image",
                        storytelling_model=f"arrival -> {brief.conversion_objective}",
                        interaction_concepts=[],
                        motion_concepts=[],
                        responsive_adaptation="to be interpreted by the frontend engine; see develop_direction",
                    ),
                    content_strategy=ContentStrategy(
                        hierarchy="; ".join(brief.required_sections) or "hero; cta",
                        primary_user_journey=f"arrival -> {brief.conversion_objective}",
                        conversion_strategy=brief.conversion_objective,
                    ),
                    references=[job.result_url] if job.result_url else [],
                    constraints=constraints_for_brief(brief),
                    provider_metadata={
                        "provider": self.name.value,
                        "job_type": self._image_model,
                        "job_id": job.job_id,
                        "angle": angle,
                    },
                    generation_metadata={
                        "credits_used": credits,
                        "duration_ms": duration_ms,
                        "stage": "initial_direction",
                        "iteration": iteration,
                    },
                )
            )

        if not candidates:
            raise RuntimeError("HiggsfieldCreativeDirector produced no candidates — see budget/CLI failure above.")
        return candidates

    def develop_direction(
        self,
        selected: CreativeDirection,
        brief: CreativeBrief,
        assets: Sequence[CreativeBriefAsset],
        budget: CreativeBudget,
    ) -> CreativeDirection:
        del assets
        developed = selected.model_copy(deep=True)
        anchor_job_id = selected.provider_metadata.get("job_id")
        continuation = selected.concept.rationale

        for iteration, angle in enumerate(_DEVELOP_ANGLES, start=1):
            prompt = _build_prompt(brief, angle, continuation_of=f"{continuation} ({brief.business_name})")
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt, reference=anchor_job_id, budget=budget, operation="develop_direction", iteration=iteration
                )
            except Exception:  # noqa: BLE001 — stop deepening, keep whatever references were already gathered
                budget.record_failure(
                    provider=self.name.value,
                    operation="develop_direction",
                    model=self._image_model,
                    iteration=iteration,
                )
                break
            if job.result_url:
                developed.references.append(job.result_url)
            developed.generation_metadata = {
                **developed.generation_metadata,
                f"develop_iteration_{iteration}_credits": credits,
                f"develop_iteration_{iteration}_duration_ms": duration_ms,
            }

        developed.generation_metadata["stage"] = "developed"
        return developed
