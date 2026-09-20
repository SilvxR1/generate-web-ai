"""GenerationContract (P2.5) — the complete, provider-independent statement
of what a provider is being asked to generate, made inspectable BEFORE any
provider execution.

It gathers the decisions the earlier layers made — asset purpose, visual
intent, the single visual subject, subject grounding, the scene plan, text and
interface policy, brand direction, reference requirements, the references
actually selected, and output requirements — and it is validated before a
billable submission. Validation is STRUCTURAL/SEMANTIC only: it rejects a
contract that cannot honestly be executed or that contradicts itself (for
example a scene that needs exact product fidelity but has no grounded
reference, or a HERO scene whose own description asks for a webpage). It is not
visual QA of the eventual image and gives no guarantee about what a model
will draw.

Provider/model details are deliberately absent: the contract exists before
provider translation, and the capability router only consumes its
requirements.
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.domain.creative.reference_strategy import ReferencePolicy, ReferenceStrategy
from app.domain.creative.scene_plan import VisualScenePlan
from app.domain.creative.spec import (
    CreativeGenerationSpec,
    InterfacePolicy,
    OutputRequirements,
    ReferenceSpec,
    ReferenceUsage,
    TextPolicy,
)
from app.domain.creative.visual_intent import SubjectGrounding, VisualIntent, VisualIntentKind
from app.domain.creative.visual_subject import VisualSubject
from app.domain.enums import AssetPurpose, BrandStrategy, CreativeLevel

GENERATION_CONTRACT_VERSION = "p2.5-v1"

# Words that would make a scene description itself ask for an interface / text.
_INTERFACE_WORDS = re.compile(
    r"(?<!\w)(website|webpage|web page|browser|screens?|interface|dashboard|navigation|menus?|buttons?|ui|"
    r"ecommerce|e-commerce|page layout)(?!\w)",
    re.IGNORECASE,
)
_TEXT_WORDS = re.compile(
    r"(?<!\w)(text|lettering|captions?|headlines?|headings?|typography|slogans?|signs?|labels?|logos?|watermarks?)(?!\w)",
    re.IGNORECASE,
)


class GenerationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = GENERATION_CONTRACT_VERSION
    purpose: AssetPurpose
    visual_intent: VisualIntentKind
    subject: VisualSubject
    grounding: SubjectGrounding
    scene: VisualScenePlan
    text_policy: TextPolicy
    interface_policy: InterfacePolicy
    brand_mode: BrandStrategy
    creative_level: CreativeLevel
    reference_policy: ReferencePolicy
    requires_visual_reference: bool
    # References actually selected for the provider (ids/roles only).
    provider_references: tuple[ReferenceSpec, ...] = ()
    output: OutputRequirements

    def with_scene(self, scene: VisualScenePlan) -> "GenerationContract":
        return self.model_copy(update={"scene": scene})

    def with_provider_references(self, references: Sequence[ReferenceSpec]) -> "GenerationContract":
        return self.model_copy(update={"provider_references": tuple(references)})


def build_generation_contract(
    *,
    spec: CreativeGenerationSpec,
    intent: VisualIntent,
    subject: VisualSubject,
    scene: VisualScenePlan,
    strategy: ReferenceStrategy,
    provider_references: Sequence[ReferenceSpec] | None = None,
) -> GenerationContract:
    return GenerationContract(
        purpose=spec.purpose,
        visual_intent=intent.kind,
        subject=subject,
        grounding=intent.grounding,
        scene=scene,
        text_policy=spec.text_policy,
        interface_policy=spec.interface_policy,
        brand_mode=spec.brand_mode,
        creative_level=spec.creative_level,
        reference_policy=strategy.policy,
        requires_visual_reference=strategy.requires_visual_reference,
        provider_references=tuple(spec.reference_assets if provider_references is None else provider_references),
        output=spec.output,
    )


class ContractIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    detail: str


class InvalidGenerationContractError(Exception):
    """Raised before any provider submission: nothing has been spent."""

    def __init__(self, issues: Sequence[ContractIssue]) -> None:
        super().__init__("; ".join(f"{issue.code}: {issue.detail}" for issue in issues))
        self.issues = list(issues)
        self.reason_code = self.issues[0].code if self.issues else "invalid_generation_contract"


def _scene_text(scene: VisualScenePlan) -> str:
    fields = (
        scene.medium,
        scene.primary_subject,
        scene.subject_treatment,
        scene.environment,
        scene.composition,
        scene.placement,
        scene.negative_space,
        scene.framing,
        scene.lighting,
        scene.depth,
        scene.material_emphasis,
        scene.brand_guidance,
        scene.safe_area,
    )
    return " . ".join(field for field in fields if field)


def validate_generation_contract(
    contract: GenerationContract, *, candidate_aspect_ratios: Sequence[frozenset[str] | None] | None = None
) -> list[ContractIssue]:
    """Every structural problem found (empty means valid). Pure."""
    issues: list[ContractIssue] = []
    grounded = contract.grounding is SubjectGrounding.GROUNDED

    if contract.purpose is AssetPurpose.PRODUCT and not grounded:
        issues.append(
            ContractIssue(
                code="product_requires_grounded_reference",
                detail="A PRODUCT visual needs a real product reference; the subject is not grounded.",
            )
        )
    if contract.scene.requires_fidelity and not grounded:
        issues.append(
            ContractIssue(
                code="fidelity_requires_grounded_reference",
                detail="The scene needs exact product fidelity but the subject grounding is not 'grounded'.",
            )
        )

    scene_text = _scene_text(contract.scene)
    if contract.interface_policy is InterfacePolicy.NO_INTERFACE_DEPICTION and _INTERFACE_WORDS.search(scene_text):
        issues.append(
            ContractIssue(
                code="scene_requests_interface",
                detail="The scene description asks for an interface, page or website.",
            )
        )
    if contract.text_policy is TextPolicy.NO_GENERATED_TEXT and _TEXT_WORDS.search(scene_text):
        issues.append(
            ContractIssue(code="scene_requests_text", detail="The scene description asks for text, signs or logos.")
        )

    if contract.reference_policy is ReferencePolicy.NO_VISUAL_REFERENCE and contract.provider_references:
        issues.append(
            ContractIssue(
                code="reference_policy_conflict",
                detail="The strategy allows no visual reference but references were selected.",
            )
        )
    if contract.requires_visual_reference and not contract.provider_references:
        issues.append(
            ContractIssue(
                code="required_reference_missing",
                detail="A reference is required for fidelity but none is selected.",
            )
        )
    if any(ref.usage in (ReferenceUsage.IDENTITY, ReferenceUsage.PALETTE) for ref in contract.provider_references):
        issues.append(
            ContractIssue(
                code="brand_mark_as_provider_reference",
                detail="A brand mark is a brand source, never a provider reference.",
            )
        )

    if candidate_aspect_ratios is not None:
        ratio = contract.output.aspect_ratio
        if not any(known is None or ratio in known for known in candidate_aspect_ratios):
            issues.append(
                ContractIssue(
                    code="aspect_ratio_unsupported_by_all_models",
                    detail=f"No candidate model supports the {ratio} aspect ratio.",
                )
            )
    return issues


def assert_valid_generation_contract(
    contract: GenerationContract, *, candidate_aspect_ratios: Sequence[frozenset[str] | None] | None = None
) -> None:
    issues = validate_generation_contract(contract, candidate_aspect_ratios=candidate_aspect_ratios)
    if issues:
        raise InvalidGenerationContractError(issues)
