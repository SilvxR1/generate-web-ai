"""HiggsfieldCliCreativeDirector / HiggsfieldApiCreativeDirector — the real
Higgsfield-backed CreativeDirectorProvider implementations (P2.2/P2.3,
P2.1), sharing one orchestration base (_HiggsfieldDirectorBase) over two
interchangeable generation backends:

  - HiggsfieldApiCreativeDirector (P2.1, PRODUCTION): the official
    Higgsfield REST API (app.creative.higgsfield.api_client.HiggsfieldApiClient),
    authenticated with a server-side API key pair. This is what
    app.dependencies.get_optional_higgsfield_director constructs whenever
    HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are configured.
  - HiggsfieldCliCreativeDirector (dev/local/manual real_provider test
    ONLY): the `higgsfield` CLI's own already-authenticated local OAuth
    session (app.creative.higgsfield.cli.HiggsfieldCli) — never selected
    in production; see docs/higgsfield-integration.md for why.

Workflow (shared by both, P2.3):
  STEP A: create_directions — three distinct prompt explorations, each
    grounded in real CreativeBrief facts (never generic), each costed
    *before* the real generation call it pays for, recorded on the
    caller's CreativeBudget.
  STEP D: develop_direction — three further explorations anchored to the
    *same* generated reference once a direction is selected, deepening
    detail/composition rather than starting a new concept.

Never asks Higgsfield to choose one of this platform's own preexisting
design families/templates — every prompt is built from `brief`'s real
facts plus an explicit instruction to propose a genuinely different
composition/interaction/visual-metaphor concept, and the resulting
CreativeDirection's `visual_language`/`experience` fields are populated
from that same prompt text (traceable, never separately invented).
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from app.creative.director import CreativeDirectorProvider
from app.creative.factual_safety import constraints_for_brief
from app.creative.higgsfield.api_client import DEFAULT_JOB_TYPE, HiggsfieldApiClient
from app.creative.higgsfield.cli import HiggsfieldCli, resolve_local_reference
from app.creative.higgsfield.models import HiggsfieldJobResult
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.enums import AssetCategory, AssetKind, CreativeProviderName

CLI_DEFAULT_IMAGE_MODEL = "nano_banana_pro"

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


class _HiggsfieldDirectorBase(CreativeDirectorProvider, ABC):
    """Shared create_directions/develop_direction orchestration — angle
    selection, prompt building, budget bookkeeping, CreativeDirection
    assembly — identical regardless of which generation backend a
    subclass wraps. Every subclass supplies only: how to estimate a
    call's cost, how to actually run one generation, which reference
    image URL(s)/path(s) to send, and what to anchor a develop_direction
    continuation on."""

    name = CreativeProviderName.HIGGSFIELD
    _credits_are_estimated: bool = False

    @property
    @abstractmethod
    def _model_label(self) -> str:
        """Recorded on CreativeBudgetCallRecord.model / generation_metadata
        — never a credential, just which model/job_type actually ran."""

    @abstractmethod
    def _estimate_cost(self, prompt: str) -> float:
        """Must return a real, already-known-or-conservatively-estimated
        cost BEFORE the call it pays for — CreativeBudget.record_spend's
        own contract. Never fabricates a number that could be an
        under-estimate large enough to blow the caller's real intent."""

    @abstractmethod
    def _create_job(self, prompt: str, references: list[str]) -> HiggsfieldJobResult:
        """Runs exactly one real, credit-consuming generation call and
        blocks until it reaches a terminal state."""

    @abstractmethod
    def _reference_urls_for(self, assets: Sequence[CreativeBriefAsset]) -> list[str]:
        """Which reference material to ground the *first* exploration
        call in — never every asset in the library (see each subclass's
        own docstring)."""

    @abstractmethod
    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        """Which reference(s) continue the *same* already-selected
        direction during develop_direction — never a fresh, unrelated
        asset selection."""

    def _spend_and_create(
        self, prompt: str, *, references: list[str], budget: CreativeBudget, operation: str, iteration: int
    ) -> tuple[HiggsfieldJobResult, float, int]:
        started = time.monotonic()
        credits = self._estimate_cost(prompt)
        budget.record_spend(
            credits, provider=self.name.value, operation=operation, model=self._model_label, iteration=iteration
        )
        job = self._create_job(prompt, references)
        duration_ms = int((time.monotonic() - started) * 1000)
        return job, credits, duration_ms

    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        references = self._reference_urls_for(assets)
        candidates: list[CreativeDirection] = []

        for iteration, angle in enumerate(_EXPLORATION_ANGLES, start=1):
            prompt = _build_prompt(brief, angle)
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt, references=references, budget=budget, operation="create_directions", iteration=iteration
                )
            except Exception:  # noqa: BLE001 — budget refusal or a real backend failure both stop exploration here
                budget.record_failure(
                    provider=self.name.value,
                    operation="create_directions",
                    model=self._model_label,
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
                        "job_type": self._model_label,
                        "job_id": job.job_id,
                        "angle": angle,
                    },
                    generation_metadata={
                        "credits_used": credits,
                        "credits_are_estimated": self._credits_are_estimated,
                        "duration_ms": duration_ms,
                        "stage": "initial_direction",
                        "iteration": iteration,
                    },
                )
            )

        if not candidates:
            raise RuntimeError(
                f"{type(self).__name__} produced no candidates — see budget/backend failure above."
            )
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
        anchor = self._anchor_for_develop(selected)
        continuation = selected.concept.rationale

        for iteration, angle in enumerate(_DEVELOP_ANGLES, start=1):
            prompt = _build_prompt(brief, angle, continuation_of=f"{continuation} ({brief.business_name})")
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt, references=anchor, budget=budget, operation="develop_direction", iteration=iteration
                )
            except Exception:  # noqa: BLE001 — stop deepening, keep whatever references were already gathered
                budget.record_failure(
                    provider=self.name.value,
                    operation="develop_direction",
                    model=self._model_label,
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


class HiggsfieldCliCreativeDirector(_HiggsfieldDirectorBase):
    """Dev/local/manual real_provider test ONLY — never the production
    path (see module docstring and docs/higgsfield-integration.md)."""

    _credits_are_estimated = False

    def __init__(
        self, cli: HiggsfieldCli, *, image_model: str = CLI_DEFAULT_IMAGE_MODEL, local_storage_root: Path | None = None
    ) -> None:
        self._cli = cli
        self._image_model = image_model
        self._local_storage_root = local_storage_root

    @property
    def _model_label(self) -> str:
        return self._image_model

    def _estimate_cost(self, prompt: str) -> float:
        return self._cli.estimate_cost(self._image_model, prompt=prompt)

    def _create_job(self, prompt: str, references: list[str]) -> HiggsfieldJobResult:
        return self._cli.create(
            self._image_model, prompt=prompt, image_references=references or None, aspect_ratio="16:9"
        )

    def _reference_urls_for(self, assets: Sequence[CreativeBriefAsset]) -> list[str]:
        if self._local_storage_root is None:
            return []
        preferred = sorted(assets, key=lambda asset: 0 if asset.kind is AssetKind.LOGO else 1)
        for asset in preferred:
            local_path = resolve_local_reference(asset.url, local_storage_root=self._local_storage_root)
            if local_path:
                return [local_path]
        return []

    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        # The CLI auto-resolves a previous job id as a reference — never a
        # re-upload of the same generated image.
        job_id = selected.provider_metadata.get("job_id")
        return [job_id] if job_id else []


def _asset_priority(asset: CreativeBriefAsset) -> int:
    if asset.kind is AssetKind.LOGO:
        return 0
    if asset.category in (AssetCategory.HERO_CANDIDATE, AssetCategory.PRODUCT):
        return 1
    if asset.category is AssetCategory.LOW_QUALITY:
        return 99
    return 2


class HiggsfieldApiCreativeDirector(_HiggsfieldDirectorBase):
    """PRODUCTION path (P2.1): the official Higgsfield REST API. See
    module docstring."""

    _credits_are_estimated = True

    def __init__(
        self,
        client: HiggsfieldApiClient,
        *,
        job_type: str = DEFAULT_JOB_TYPE,
        estimated_credits_per_call: float = 2.0,
        asset_base_url: str = "",
        max_reference_assets: int = 3,
    ) -> None:
        self._client = client
        self._job_type = job_type
        self._estimated_credits_per_call = estimated_credits_per_call
        self._asset_base_url = asset_base_url.rstrip("/")
        self._max_reference_assets = max_reference_assets

    @property
    def _model_label(self) -> str:
        return self._job_type

    def _estimate_cost(self, prompt: str) -> float:
        del prompt  # No REST cost-estimate endpoint exists — see this class's own _credits_are_estimated flag.
        return self._estimated_credits_per_call

    def _create_job(self, prompt: str, references: list[str]) -> HiggsfieldJobResult:
        return self._client.create(
            self._job_type, prompt=prompt, image_references=references or None, aspect_ratio="16:9"
        )

    def _reference_urls_for(self, assets: Sequence[CreativeBriefAsset]) -> list[str]:
        """Phase 4: real client imagery, by public HTTPS URL — logo first,
        then a representative hero/product image, then a small number of
        other strong real images. Never every asset in the library, and
        never a fabricated placeholder when real assets exist."""
        ordered = sorted(
            (a for a in assets if a.kind is AssetKind.LOGO or a.category is not AssetCategory.LOW_QUALITY),
            key=_asset_priority,
        )
        urls: list[str] = []
        seen: set[str] = set()
        for asset in ordered:
            url = self._absolute_asset_url(asset.url)
            if url and url not in seen:
                urls.append(url)
                seen.add(url)
            if len(urls) >= self._max_reference_assets:
                break
        return urls

    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        # REST has no "reference by job id" concept — continuation is
        # anchored on the previously generated image's own public URL,
        # which `references[0]` already is (Higgsfield hosts it for the
        # output-retention window; see docs/higgsfield-integration.md).
        return [selected.references[0]] if selected.references else []

    def _absolute_asset_url(self, asset_url: str) -> str | None:
        if asset_url.startswith("https://"):
            return asset_url
        if asset_url.startswith("http://"):
            return None  # Never send a plaintext http reference — Higgsfield must be able to fetch over https.
        if not self._asset_base_url:
            return None
        return f"{self._asset_base_url}{asset_url}"
