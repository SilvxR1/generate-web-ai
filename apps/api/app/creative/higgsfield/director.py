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

P2.2: this module is a PROVIDER ADAPTER, not the creative system.
Creative strategy — asset purpose, brand mode, reference selection and
semantics, text/logo policy, negative constraints — lives in the
provider-independent domain layer (app.domain.creative.spec /
prompt_composer). This module only: asks that layer for a
CreativeGenerationSpec, resolves the spec's ranked references to
provider-usable locations (presigned R2 URL / local path) within the
model's own limit, translates the composed prompt into Higgsfield's
payload (app.creative.higgsfield.translation), runs the job, and records
provider metadata, budget and provenance.

Workflow (shared by both, P2.3):
  STEP A: create_directions — three visual explorations, each composed
    from real CreativeBrief facts, each costed *before* the real
    generation call it pays for, recorded on the caller's CreativeBudget.
  STEP D: develop_direction — three further explorations anchored to the
    *same* generated reference once a direction is selected.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID

from app.creative.director import CreativeDirectorProvider
from app.creative.factual_safety import constraints_for_brief
from app.creative.higgsfield.api_client import (
    DEFAULT_JOB_TYPE,
    HiggsfieldApiClient,
    HiggsfieldApiUnavailableError,
    HiggsfieldModelConfig,
    resolve_model_config,
)
from app.creative.higgsfield.cli import HiggsfieldCli, resolve_local_reference
from app.creative.higgsfield.models import HiggsfieldJobResult
from app.creative.higgsfield.translation import to_higgsfield_prompt
from app.domain.creative import CreativeBrief, CreativeBriefAsset
from app.domain.creative.asset_validation import GeneratedAssetInfo, GeneratedAssetValidator, MetadataAssetValidator
from app.domain.creative.budget import CreativeBudget
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.domain.creative.prompt_composer import DEVELOP_ANGLES, EXPLORATION_ANGLES, compose_prompt
from app.domain.creative.provenance import COST_SEMANTICS, build_creative_provenance
from app.domain.creative.spec import (
    CreativeGenerationSpec,
    ReferenceSpec,
    ReferenceUsage,
    build_generation_spec,
)
from app.domain.enums import AssetPurpose, BrandStrategy, CreativeLevel, CreativeProviderName
from app.storage.provider import StorageProvider

CLI_DEFAULT_IMAGE_MODEL = "nano_banana_pro"

_DEFAULT_REFERENCE_CANDIDATES = 3


def _narrative(brief: CreativeBrief, spec: CreativeGenerationSpec, angle: str) -> str:
    """Human-readable concept narrative (business context for Studio and
    the frontend engine). NOT the provider prompt — that is composed
    separately and deliberately omits the business name."""
    parts = [f"Business: {brief.business_name} ({brief.industry})."]
    if brief.description:
        parts.append(f"Description: {brief.description}.")
    if brief.target_customer:
        parts.append(f"Target customer: {brief.target_customer}.")
    parts.append(
        f"Visual exploration for the {spec.purpose.value} image ({spec.brand_mode.value} brand mode): {angle}."
    )
    return " ".join(parts)


def _asset_info(job: HiggsfieldJobResult, *, model: str) -> GeneratedAssetInfo:
    images = job.raw.get("images") if isinstance(job.raw, dict) else None
    if isinstance(images, list):
        urls = [image["url"] for image in images if isinstance(image, dict) and isinstance(image.get("url"), str)]
        first = images[0] if images and isinstance(images[0], dict) else {}
    else:
        urls = [job.result_url] if job.result_url else []
        first = {}
    width, height = first.get("width"), first.get("height")
    return GeneratedAssetInfo(
        provider_completed=job.status == "completed",
        result_urls=urls,
        width=width if isinstance(width, int) else None,
        height=height if isinstance(height, int) else None,
        job_id=job.job_id,
        model=model,
    )


class _HiggsfieldDirectorBase(CreativeDirectorProvider, ABC):
    """Shared create_directions/develop_direction orchestration — spec
    preparation, budget bookkeeping, validation, CreativeDirection
    assembly — identical regardless of which generation backend a
    subclass wraps. Every subclass supplies only backend-specific
    mechanics: cost estimate, running one generation, resolving
    references to locations that backend can use, and its own limits."""

    name = CreativeProviderName.HIGGSFIELD
    _credits_are_estimated: bool = False
    _validator: GeneratedAssetValidator = MetadataAssetValidator()

    @property
    @abstractmethod
    def _model_label(self) -> str:
        """Recorded on CreativeBudgetCallRecord.model / generation_metadata
        — never a credential, just which model/job_type actually ran."""

    @property
    @abstractmethod
    def _reference_candidate_limit(self) -> int:
        """How many ranked reference candidates the spec should carry."""

    @property
    @abstractmethod
    def _max_provider_references(self) -> int:
        """How many references the backend/model will actually accept."""

    @abstractmethod
    def _estimate_cost(self, prompt: str) -> float:
        """Must return a real, already-known-or-conservatively-estimated
        cost BEFORE the call it pays for — CreativeBudget.record_spend's
        own contract. Never fabricates a number that could be an
        under-estimate large enough to blow the caller's real intent."""

    @abstractmethod
    def _create_job(self, prompt: str, references: list[str], aspect_ratio: str | None) -> HiggsfieldJobResult:
        """Runs exactly one real, credit-consuming generation call and
        blocks until it reaches a terminal state."""

    @abstractmethod
    def _resolve_references(
        self, references: Sequence[ReferenceSpec], assets_by_id: Mapping[UUID, CreativeBriefAsset]
    ) -> list[tuple[ReferenceSpec, str]]:
        """Resolve the spec's ranked reference candidates, in order, to
        locations this backend can use — silently skipping any it cannot
        resolve (a next-ranked candidate then takes its place)."""

    @abstractmethod
    def _supported_aspect_ratio(self, requested: str) -> str | None:
        """`requested` if this backend/model supports it, else None (the
        parameter is then omitted and the model's own default applies)."""

    @abstractmethod
    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        """Which reference(s) continue the *same* already-selected
        direction during develop_direction — never a fresh, unrelated
        asset selection."""

    def _prepare_spec(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset]
    ) -> tuple[CreativeGenerationSpec, list[str]]:
        spec = build_generation_spec(brief, assets, max_reference_candidates=self._reference_candidate_limit)
        resolved = self._resolve_references(spec.reference_assets, {asset.id: asset for asset in assets})
        used = resolved[: self._max_provider_references]
        return spec.with_used_references([reference for reference, _ in used]), [location for _, location in used]

    def _spend_and_create(
        self,
        prompt: str,
        *,
        references: list[str],
        aspect_ratio: str | None,
        budget: CreativeBudget,
        operation: str,
        iteration: int,
    ) -> tuple[HiggsfieldJobResult, float, int]:
        started = time.monotonic()
        credits = self._estimate_cost(prompt)
        budget.record_spend(
            credits, provider=self.name.value, operation=operation, model=self._model_label, iteration=iteration
        )
        job = self._create_job(prompt, references, aspect_ratio)
        duration_ms = int((time.monotonic() - started) * 1000)
        return job, credits, duration_ms

    def create_directions(
        self, brief: CreativeBrief, assets: Sequence[CreativeBriefAsset], budget: CreativeBudget
    ) -> list[CreativeDirection]:
        spec, references = self._prepare_spec(brief, assets)
        aspect_ratio = self._supported_aspect_ratio(spec.output.aspect_ratio)
        candidates: list[CreativeDirection] = []
        last_error: Exception | None = None

        for iteration, angle in enumerate(EXPLORATION_ANGLES, start=1):
            composed = compose_prompt(brief, spec, angle=angle)
            prompt = to_higgsfield_prompt(composed)
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt,
                    references=references,
                    aspect_ratio=aspect_ratio,
                    budget=budget,
                    operation="create_directions",
                    iteration=iteration,
                )
            except Exception as exc:  # noqa: BLE001 — budget refusal or a real backend failure both stop exploration here
                last_error = exc
                budget.record_failure(
                    provider=self.name.value,
                    operation="create_directions",
                    model=self._model_label,
                    iteration=iteration,
                )
                break

            validation = self._validator.validate(spec, _asset_info(job, model=self._model_label))
            provenance = build_creative_provenance(
                spec=spec,
                composed=composed,
                validation=validation,
                provider=self.name.value,
                model=self._model_label,
                job_id=job.job_id,
                estimated_generation_units=credits,
                angle=angle,
            )
            candidates.append(
                CreativeDirection(
                    concept=CreativeConcept(
                        name=f"{brief.business_name} — direction {iteration}",
                        rationale=f"Explored via {angle}.",
                        narrative=_narrative(brief, spec, angle),
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
                        navigation_concept="to be interpreted from the reference image",
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
                        "purpose": spec.purpose.value,
                    },
                    generation_metadata={
                        "credits_used": credits,
                        "credits_are_estimated": self._credits_are_estimated,
                        "estimated_generation_units": credits,
                        "cost_semantics": COST_SEMANTICS,
                        "duration_ms": duration_ms,
                        "stage": "initial_direction",
                        "iteration": iteration,
                        "creative_spec": provenance,
                    },
                )
            )

        if not candidates:
            # Re-raise the real, specific failure (a CreativeProviderError
            # subclass — e.g. HiggsfieldInsufficientCreditsError,
            # HiggsfieldModelUnavailableError, BudgetExceededError) instead
            # of a bare RuntimeError: the caller (app.routers.creative)
            # maps CreativeProviderError/BudgetExceededError to a
            # structured AppError response. A bare RuntimeError would
            # escape that mapping entirely and fall through to FastAPI's
            # generic catch-all handler — which, in this app's actual
            # Starlette middleware stack, produces a response that never
            # receives CORS headers (Starlette's ServerErrorMiddleware,
            # which owns the bare-Exception handler, sits outside
            # CORSMiddleware), making the browser report a misleading
            # "network failure" instead of the real error. See hotfix
            # P2/creative-directions-500's own report for the full,
            # empirically-verified chain.
            if last_error is not None:
                raise last_error
            raise RuntimeError(  # pragma: no cover — defensive only; every real failure path sets last_error
                f"{type(self).__name__} produced no candidates and no failure was recorded."
            )
        return candidates

    def _develop_spec(
        self, selected: CreativeDirection, brief: CreativeBrief, anchor: list[str]
    ) -> tuple[CreativeBrief, CreativeGenerationSpec]:
        """A continuation keeps the intent of the direction it deepens
        (purpose/brand mode/level recorded in its provenance), never
        whatever the request-time default happens to be."""
        recorded = selected.generation_metadata.get("creative_spec")
        recorded = recorded if isinstance(recorded, dict) else {}
        updates: dict = {}
        try:
            updates["asset_purpose"] = AssetPurpose(recorded["purpose"])
            updates["brand_strategy"] = BrandStrategy(recorded["brand_mode"])
            updates["creative_level"] = CreativeLevel(recorded["creative_level"])
        except (KeyError, ValueError):
            updates = {}
        effective_brief = brief.model_copy(update=updates) if updates else brief
        spec = build_generation_spec(effective_brief, [], max_reference_candidates=0)
        if anchor:
            spec = spec.with_used_references(
                [ReferenceSpec(asset_id=None, usage=ReferenceUsage.STYLE, source="previous_generation")]
            )
        return effective_brief, spec

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
        effective_brief, spec = self._develop_spec(selected, brief, anchor)
        aspect_ratio = self._supported_aspect_ratio(spec.output.aspect_ratio)
        continuation = selected.concept.rationale.rstrip(".")

        for iteration, angle in enumerate(DEVELOP_ANGLES, start=1):
            composed = compose_prompt(effective_brief, spec, angle=angle, continuation_of=continuation)
            prompt = to_higgsfield_prompt(composed)
            try:
                job, credits, duration_ms = self._spend_and_create(
                    prompt,
                    references=anchor,
                    aspect_ratio=aspect_ratio,
                    budget=budget,
                    operation="develop_direction",
                    iteration=iteration,
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
                "develop_prompt_version": composed.version,
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

    @property
    def _reference_candidate_limit(self) -> int:
        return _DEFAULT_REFERENCE_CANDIDATES

    @property
    def _max_provider_references(self) -> int:
        return 1

    def _estimate_cost(self, prompt: str) -> float:
        return self._cli.estimate_cost(self._image_model, prompt=prompt)

    def _create_job(self, prompt: str, references: list[str], aspect_ratio: str | None) -> HiggsfieldJobResult:
        return self._cli.create(
            self._image_model, prompt=prompt, image_references=references or None, aspect_ratio=aspect_ratio
        )

    def _supported_aspect_ratio(self, requested: str) -> str | None:
        return requested

    def _resolve_references(
        self, references: Sequence[ReferenceSpec], assets_by_id: Mapping[UUID, CreativeBriefAsset]
    ) -> list[tuple[ReferenceSpec, str]]:
        if self._local_storage_root is None:
            return []
        resolved: list[tuple[ReferenceSpec, str]] = []
        for reference in references:
            asset = assets_by_id.get(reference.asset_id) if reference.asset_id else None
            if asset is None:
                continue
            local_path = resolve_local_reference(asset.url, local_storage_root=self._local_storage_root)
            if local_path:
                resolved.append((reference, local_path))
        return resolved

    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        # The CLI auto-resolves a previous job id as a reference — never a
        # re-upload of the same generated image.
        job_id = selected.provider_metadata.get("job_id")
        return [job_id] if job_id else []


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
        max_reference_assets: int = _DEFAULT_REFERENCE_CANDIDATES,
        storage: StorageProvider | None = None,
        presigned_url_expires_in_seconds: int = 600,
    ) -> None:
        self._client = client
        self._job_type = job_type
        self._estimated_credits_per_call = estimated_credits_per_call
        self._asset_base_url = asset_base_url.rstrip("/")
        self._max_reference_assets = max_reference_assets
        # Phase 5 (private provider references): when set, this is the
        # SAME StorageProvider app.dependencies.get_storage_provider would
        # construct right now — used only to mint a short-lived presigned
        # GET URL for an asset this backend itself wrote (see
        # _resolve_reference_url below). None (the default, and every
        # existing call site before this parameter existed) falls back to
        # always sending the asset's own already-stored URL, exactly as
        # before.
        self._storage = storage
        self._presigned_url_expires_in_seconds = presigned_url_expires_in_seconds

    @property
    def _model_label(self) -> str:
        return self._job_type

    def _model_config(self) -> HiggsfieldModelConfig | None:
        """None for a model id outside the allowlist: submit() raises the
        structured HiggsfieldApiUnavailableError for it before any HTTP
        request, exactly as it always has — never raised from here, so
        the failure keeps flowing through the same budget/fallback path."""
        try:
            return resolve_model_config(self._job_type)
        except HiggsfieldApiUnavailableError:
            return None

    @property
    def _reference_candidate_limit(self) -> int:
        return self._max_reference_assets

    @property
    def _max_provider_references(self) -> int:
        config = self._model_config()
        if config is None:
            return self._max_reference_assets
        return config.max_reference_images if config.supports_reference_images else 0

    def _estimate_cost(self, prompt: str) -> float:
        del prompt  # No REST cost-estimate endpoint exists — see this class's own _credits_are_estimated flag.
        return self._estimated_credits_per_call

    def _create_job(self, prompt: str, references: list[str], aspect_ratio: str | None) -> HiggsfieldJobResult:
        return self._client.create(
            self._job_type, prompt=prompt, image_references=references or None, aspect_ratio=aspect_ratio
        )

    def _supported_aspect_ratio(self, requested: str) -> str | None:
        config = self._model_config()
        if config is None or requested in config.supported_aspect_ratios:
            return requested
        return None

    def _resolve_references(
        self, references: Sequence[ReferenceSpec], assets_by_id: Mapping[UUID, CreativeBriefAsset]
    ) -> list[tuple[ReferenceSpec, str]]:
        """The spec has already ranked and classified the candidates
        (purpose/usage aware); this only turns each into a URL Higgsfield
        can fetch, skipping any that cannot be resolved — never a
        fabricated placeholder when real assets exist."""
        resolved: list[tuple[ReferenceSpec, str]] = []
        seen: set[str] = set()
        for reference in references:
            asset = assets_by_id.get(reference.asset_id) if reference.asset_id else None
            if asset is None:
                continue
            url = self._resolve_reference_url(asset)
            if url and url not in seen:
                resolved.append((reference, url))
                seen.add(url)
        return resolved

    def _anchor_for_develop(self, selected: CreativeDirection) -> list[str]:
        # REST has no "reference by job id" concept — continuation is
        # anchored on the previously generated image's own public URL,
        # which `references[0]` already is (Higgsfield hosts it for the
        # output-retention window; see docs/higgsfield-integration.md).
        return [selected.references[0]] if selected.references else []

    def _resolve_reference_url(self, asset: CreativeBriefAsset) -> str | None:
        """Phase 5 (private provider references): a business asset this
        backend actually wrote to its current storage provider is fetched
        by Higgsfield through a short-lived presigned GET URL — the
        customer never manages or even sees this URL, and it stops
        working shortly after Higgsfield uses it — rather than that
        asset needing to be permanently, unlistedly public. Only applies
        when `asset.storage_provider` matches this director's own current
        storage provider (never guessed for a legacy row, an
        externally-hosted URL, or a provider migration in progress);
        every other case falls back to `_absolute_asset_url(asset.url)`
        unchanged, exactly as before this method existed. A provider with
        no signing concept (LocalStorageProvider) returns None from
        presigned_url, which also falls back to the unchanged URL."""
        if self._storage is not None and asset.storage_key and asset.storage_provider == self._storage.provider_name:
            presigned = self._storage.presigned_url(
                asset.storage_key, expires_in_seconds=self._presigned_url_expires_in_seconds
            )
            if presigned:
                return presigned
        return self._absolute_asset_url(asset.url)

    def _absolute_asset_url(self, asset_url: str) -> str | None:
        if asset_url.startswith("https://"):
            return asset_url
        if asset_url.startswith("http://"):
            return None  # Never send a plaintext http reference — Higgsfield must be able to fetch over https.
        if not self._asset_base_url:
            return None
        return f"{self._asset_base_url}{asset_url}"
