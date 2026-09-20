"""CreativePromptComposer (P2.2 → P2.5) — renders a GenerationContract into a
structured, provider-independent ComposedCreativePrompt. Pure and
deterministic: no network, R2, provider SDK or database.

P2.5 rewrite. The composer no longer interprets business semantics or
explains our architecture: every decision has already been made upstream
(subject, scene, policies, references) and recorded in provenance. What it
renders is what the image model should DO:

- SCENE: concrete visual sentences derived from the scene plan (medium,
  subject, treatment, environment, composition, subject side, negative space,
  framing, lighting, depth, emphasis, brand direction, crop safety, aspect).
- REFERENCES: what each supplied reference is for (none for HERO).
- CONSTRAINTS: the short text / interface / scene prohibitions.

Placement is translated into composition — the provider prompt never says
"website", "webpage" or "hero"; it says where the subject sits and where the
clean space is. Decision rationale lives in provenance, not in the prompt.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.content_policy import interface_rules, render_prohibition, text_rules
from app.domain.creative.generation_contract import GenerationContract
from app.domain.creative.scene_plan import VisualScenePlan, aspect_phrase
from app.domain.creative.spec import PROMPT_VERSION, ReferenceSpec, ReferenceUsage

# Variations used when a direction is deepened (develop_direction).
DEVELOP_ANGLES: tuple[str, ...] = (
    "composed so it also holds up when cropped to a narrow portrait format",
    "a close, tactile detail of its texture and material",
    "a calmer, wider view with even more open negative space",
)


class ComposedCreativePrompt(BaseModel):
    """Structured output — every provider translates this; none reads the
    brief or the business for creative strategy."""

    model_config = ConfigDict(extra="forbid")

    version: str = PROMPT_VERSION
    scene: list[str] = Field(default_factory=list)
    reference_instructions: list[str] = Field(default_factory=list)
    # Short, final prohibitions rendered as sentences ("No text, lettering …").
    constraints: list[str] = Field(default_factory=list)
    # The same prohibitions as flat "no X" phrases, for providers that accept a
    # separate negative prompt.
    negative_constraints: list[str] = Field(default_factory=list)
    # Debug/provenance only: never URLs, credentials or business text.
    debug: dict = Field(default_factory=dict)


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text[:1].upper() + text[1:] + "." if text else ""


def _reference_instruction(index: int, total: int, reference: ReferenceSpec) -> str:
    label = "The reference image" if total == 1 else f"Reference image {index}"
    if reference.source == "previous_generation":
        return f"{label} is the previous image for this direction: keep the same scene, palette and style."
    match reference.usage:
        case ReferenceUsage.PRODUCT:
            return (
                f"{label} shows the real product: keep it the primary subject, faithful in shape, colour and detail, "
                "and add nothing invented."
            )
        case ReferenceUsage.SUBJECT:
            return f"{label} shows the real subject: keep it recognisable and faithful, and add nothing invented."
        case ReferenceUsage.COMPOSITION:
            return f"{label} is real imagery: take only its framing and balance, not its subject."
        case ReferenceUsage.STYLE:
            return f"{label} is real imagery: take only its mood, lighting and material feel, not its subject."
        case ReferenceUsage.IDENTITY | ReferenceUsage.PALETTE:
            # Safety net only: the reference strategy never sends a brand mark.
            return f"{label} is a brand mark: take only its colours and do not reproduce it."


def _scene_sentences(scene: VisualScenePlan) -> list[str]:
    head = f"{scene.medium} of {scene.primary_subject}" if scene.primary_subject else scene.medium
    parts = [
        head,
        scene.subject_treatment,
        scene.environment,
        scene.composition,
        scene.placement,
        scene.negative_space,
        scene.framing,
        scene.lighting,
        scene.depth,
        f"Emphasis on {scene.material_emphasis}" if scene.material_emphasis else "",
        f"Brand direction: {scene.brand_guidance}" if scene.brand_guidance else "",
        scene.safe_area,
        aspect_phrase(scene.aspect_ratio),
    ]
    return [sentence for sentence in (_sentence(part) for part in parts) if sentence]


def compose_prompt(
    contract: GenerationContract, *, variation: str | None = None, continuation_of: str | None = None
) -> ComposedCreativePrompt:
    scene_lines = _scene_sentences(contract.scene)
    if continuation_of:
        scene_lines.insert(0, "Continue the same visual world as the reference image.")
    if variation:
        scene_lines.append(_sentence(f"Variation: {variation}"))

    text = text_rules(contract.text_policy)
    interface = interface_rules(contract.interface_policy)
    constraints = [text.sentence(), interface.sentence(), render_prohibition(contract.scene.forbidden_elements)]
    negatives = [f"no {item}" for item in (*text.forbidden, *interface.forbidden, *contract.scene.forbidden_elements)]

    references = [
        _reference_instruction(index, len(contract.provider_references), ref)
        for index, ref in enumerate(contract.provider_references, start=1)
    ]

    return ComposedCreativePrompt(
        scene=scene_lines,
        reference_instructions=references,
        constraints=[line for line in constraints if line],
        negative_constraints=negatives,
        debug={
            "purpose": contract.purpose.value,
            "visual_intent": contract.visual_intent.value,
            "visual_subject": contract.subject.label,
            "visual_subject_source": contract.subject.source.value,
            "subject_grounding": contract.grounding.value,
            "brand_mode": contract.brand_mode.value,
            "creative_level": contract.creative_level.value,
            "text_policy": contract.text_policy.value,
            "interface_policy": contract.interface_policy.value,
            "reference_usages": [ref.usage.value for ref in contract.provider_references],
            "subject_side": contract.scene.subject_side.value,
            "business_name_in_prompt": False,
            "raw_business_description_in_prompt": False,
            "is_continuation": continuation_of is not None,
        },
    )
