"""CreativeModelRouter (P2.3) — capability-based model selection.

Requirements (derived from the generation spec and reference strategy) say
what a generation needs; registered models declare what they can do; the
router picks a model whose capabilities satisfy the requirements. There is
no `if hero: model = "..."` anywhere: routing never names a model.

HONESTY: a capability that has not been verified stays unknown (`None`).
`verified_by` records how each model's capabilities were established, and
the router prefers better-verified models when several qualify. If no
registered model satisfies the requirements the router raises
NoSuitableModelError — it never quietly sends an inappropriate asset to a
model that merely happens to accept one (the exact failure P2.1/P2.2 hit
when a logo was pushed through a reference-required model).

The configured model (HIGGSFIELD_API_MODEL) is a *preference*: it is
chosen whenever it satisfies the requirements, otherwise another registered
model that does is selected, with the reason recorded.

Pure domain code: no provider SDKs, network or persistence.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.spec import ReferenceUsage, TextPolicy


class OutputKind(StrEnum):
    IMAGE = "image"


class CapabilityVerification(StrEnum):
    """How a model's capabilities were established, best first."""

    CURRENT_OFFICIAL_SPEC = "current_official_spec"
    OBSERVED_IN_PRODUCTION = "observed_in_production"
    EARLIER_OFFICIAL_SPEC = "earlier_official_spec"


_VERIFICATION_RANK = {
    CapabilityVerification.CURRENT_OFFICIAL_SPEC: 0,
    CapabilityVerification.OBSERVED_IN_PRODUCTION: 1,
    CapabilityVerification.EARLIER_OFFICIAL_SPEC: 2,
}


@dataclass(frozen=True)
class ModelCapabilities:
    output: OutputKind
    supports_reference: bool
    # True when the model cannot run without a reference image.
    requires_reference: bool
    max_reference_images: int
    # None means unknown — never guessed.
    supported_aspect_ratios: frozenset[str] | None
    reference_roles: frozenset[ReferenceUsage] | None
    verified_by: CapabilityVerification


@dataclass(frozen=True)
class RegisteredModel:
    provider: str
    model_id: str
    capabilities: ModelCapabilities


class CreativeGenerationRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: OutputKind = OutputKind.IMAGE
    aspect_ratio: str
    text_policy: TextPolicy = TextPolicy.NO_GENERATED_TEXT
    # Subject/product fidelity needs a reference-conditioned model.
    requires_visual_reference: bool = False
    required_reference_count: int = 0
    # References that would help but are not needed for fidelity; a model
    # that cannot take them is still acceptable (they are dropped).
    optional_reference_count: int = 0


class RejectedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    reason: str


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model_id: str
    reason: str
    verified_by: str
    requirements: CreativeGenerationRequirements
    rejected: list[RejectedModel] = Field(default_factory=list)
    # True when optional references were wanted but the selected model
    # cannot take them, so generation proceeds without them.
    dropped_optional_references: bool = False


class NoSuitableModelError(Exception):
    """No registered model satisfies the requirements. Raised before any
    provider call, so nothing has been spent."""

    def __init__(self, message: str, *, reason_code: str, rejected: Sequence[RejectedModel] = ()) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.rejected = list(rejected)


NO_SUITABLE_MODEL = "no_registered_model_satisfies_requirements"


def _rejection_reason(capabilities: ModelCapabilities, requirements: CreativeGenerationRequirements) -> str | None:
    if capabilities.output is not requirements.output:
        return "output_not_supported"
    wants_reference = requirements.required_reference_count > 0 or requirements.optional_reference_count > 0
    if requirements.required_reference_count > 0:
        if (
            not capabilities.supports_reference
            or capabilities.max_reference_images < requirements.required_reference_count
        ):
            return "required_reference_not_supported"
    elif not wants_reference and capabilities.requires_reference:
        return "requires_a_reference_but_none_is_wanted"
    ratios = capabilities.supported_aspect_ratios
    if ratios is not None and requirements.aspect_ratio not in ratios:
        return "aspect_ratio_not_supported"
    return None


def select_model(
    requirements: CreativeGenerationRequirements,
    candidates: Sequence[RegisteredModel],
    *,
    preferred_model_id: str | None = None,
) -> ModelSelection:
    rejected: list[RejectedModel] = []
    satisfying: list[tuple[int, RegisteredModel]] = []
    for index, model in enumerate(candidates):
        reason = _rejection_reason(model.capabilities, requirements)
        if reason is None:
            satisfying.append((index, model))
        else:
            rejected.append(RejectedModel(model_id=model.model_id, reason=reason))

    if not satisfying:
        raise NoSuitableModelError(
            "No registered model satisfies this generation's requirements.",
            reason_code=NO_SUITABLE_MODEL,
            rejected=rejected,
        )

    wants_optional = requirements.optional_reference_count > 0 and requirements.required_reference_count == 0

    def sort_key(item: tuple[int, RegisteredModel]) -> tuple[int, int, int, int]:
        index, model = item
        caps = model.capabilities
        return (
            0 if model.model_id == preferred_model_id else 1,
            0 if (wants_optional and caps.supports_reference) else 1,
            _VERIFICATION_RANK[caps.verified_by],
            index,
        )

    _, chosen = min(satisfying, key=sort_key)
    if chosen.model_id == preferred_model_id:
        reason = "configured_model_satisfies_requirements"
    else:
        preferred_rejection = next((r.reason for r in rejected if r.model_id == preferred_model_id), None)
        reason = (
            f"configured_model_unsuitable:{preferred_rejection}; selected_by_capability"
            if preferred_rejection
            else "selected_by_capability"
        )

    return ModelSelection(
        provider=chosen.provider,
        model_id=chosen.model_id,
        reason=reason,
        verified_by=chosen.capabilities.verified_by.value,
        requirements=requirements,
        rejected=rejected,
        dropped_optional_references=wants_optional and not chosen.capabilities.supports_reference,
    )
