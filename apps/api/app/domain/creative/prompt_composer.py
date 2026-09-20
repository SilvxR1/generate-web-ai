"""CreativePromptComposer (P2.2) — turns a CreativeBrief plus a
CreativeGenerationSpec into a structured, provider-independent
ComposedCreativePrompt. Pure and deterministic: no network, R2, provider
SDK or database, so it is unit-testable in isolation. Provider adapters
(app.creative.higgsfield.translation) flatten this structure into their own
payload; no creative strategy lives in an adapter.

Two rules shape every output:

1. VERIFIED FACTS vs CREATIVE INTERPRETATION. The business-context section
   only ever states facts present on the CreativeBrief. Absence of
   information is stated as absence, never filled in. Visual metaphors and
   mood are labelled as interpretation and may not become claims.
2. THE REFERENCE IS NOT THE OUTPUT INTENT. Each supplied reference is
   described by the role it plays (ReferenceUsage). A real logo is
   authoritative brand identity: it guides palette/geometry/character and
   is never recreated — the website overlays the real logo asset itself.
"""

import re

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brand_profile import BrandVisualProfile, build_brand_visual_profile
from app.domain.creative.brief import CreativeBrief
from app.domain.creative.spec import (
    PROMPT_VERSION,
    CreativeGenerationSpec,
    ReferenceSpec,
    ReferenceUsage,
    TextPolicy,
)
from app.domain.enums import AssetPurpose, BrandStrategy, CreativeLevel

_MAX_DESCRIPTION_CHARS = 400
_MAX_SERVICES = 6

EXPLORATION_ANGLES: tuple[str, ...] = (
    "a bespoke visual metaphor drawn from the craft or product itself, expressed through abstract shape, "
    "texture and light",
    "an atmospheric, immersive scene that evokes the feeling of the business's world without depicting any "
    "specific product, person or place",
    "a calm, confident, trust-building composition with clear visual hierarchy and restrained detail",
)

DEVELOP_ANGLES: tuple[str, ...] = (
    "the same world, composed so it also holds up when cropped to a narrow portrait format",
    "the same world, as a close, tactile detail of its texture and material",
    "the same world, as a calmer, wider variant with even more open negative space",
)

_LEVEL_DIRECTION: dict[CreativeLevel, str] = {
    CreativeLevel.BASIC: "simple, clean and restrained",
    CreativeLevel.PROFESSIONAL: "polished, refined and cohesive",
    CreativeLevel.PREMIUM: "rich, carefully art-directed and distinctive",
    CreativeLevel.CINEMATIC: "cinematic, with dramatic depth, lighting and atmosphere",
}

_BRAND_MODE_DIRECTION: dict[BrandStrategy, str] = {
    BrandStrategy.PRESERVE: (
        "Stay faithful to the brand's existing visual identity: use its palette, geometric forms and character. "
        "Do not redesign, distort or reinterpret the brand mark."
    ),
    BrandStrategy.EVOLVE: (
        "Evolve the brand's visual system while keeping its recognisable DNA (palette family, shapes, character). "
        "Fresh interpretation of style and composition is welcome; do not replace or imitate the official logo."
    ),
    BrandStrategy.NEW_DIRECTION: (
        "Explore a substantially new visual direction. Any references inform context only and must not constrain "
        "it; keep every stated business fact accurate."
    ),
}

_PURPOSE_ROLE: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "the large hero image at the top of the business's website",
    AssetPurpose.SECTION: "a supporting image for one content section of the business's website",
    AssetPurpose.BACKGROUND: "a full-width background behind website content",
    AssetPurpose.PRODUCT: "a product image on the business's website",
    AssetPurpose.EDITORIAL: "an editorial, story-telling image within the business's website",
    AssetPurpose.TEXTURE: "a supporting texture or pattern surface for the business's website",
}

_PURPOSE_COMPOSITION: dict[AssetPurpose, tuple[str, ...]] = {
    AssetPurpose.HERO: (
        "Landscape composition with one strong focal subject and a clear focal hierarchy.",
        "Reserve generous, calm negative space (about a third of the frame, on one side) where the website "
        "will overlay its own heading and call-to-action.",
        "Keep important content away from the edges so the image survives responsive cropping.",
        "Visually distinctive, with cohesive lighting and moderate visual density.",
    ),
    AssetPurpose.BACKGROUND: (
        "Low visual density with soft gradations and a wide format.",
        "No central subject: keep the middle calm and place any interest toward the periphery.",
        "Provide clearly lighter and darker zones with enough contrast for overlaid website text.",
        "Crop-friendly: nothing critical near the edges; it must tolerate being scaled and cropped.",
    ),
    AssetPurpose.SECTION: (
        "Supports a single content section and stays secondary in hierarchy to the hero: calmer and less dramatic.",
        "A clear but modest focal element with balanced framing and margin for website content.",
    ),
    AssetPurpose.PRODUCT: (
        "The product is the primary subject, fully in view and unobstructed, on a strong thirds intersection "
        "or centred.",
        "Clean, uncluttered surroundings that do not compete with it; faithful proportions and colours; soft, "
        "natural lighting.",
        "Even margin around the subject.",
    ),
    AssetPurpose.EDITORIAL: (
        "Editorial, photography-led composition with a considered focal path and clear hierarchy.",
        "Natural depth and room to breathe; any text is added later by the website, never in the image.",
    ),
    AssetPurpose.TEXTURE: (
        "A seamless, abstract, supporting surface: continuous or repeating pattern with no focal subject.",
        "Even density from edge to edge, with no recognisable objects, logos or marks.",
    ),
}

_NO_TEXT_NEGATIVES: tuple[str, ...] = (
    "no words, letters, numbers or typography of any kind",
    "no captions, slogans, watermarks or signatures",
    "no fake logos or brand marks",
    "do not write or reproduce the business name",
    "no user-interface elements, buttons or browser chrome",
)

_GENERAL_NEGATIVES: tuple[str, ...] = (
    "no invented business claims, prices or offers",
    "no invented products, projects, people or testimonials",
    "no malformed or distorted geometry",
)

_LOGO_NEGATIVE = "do not recreate, redraw or approximate the official logo"


class ComposedCreativePrompt(BaseModel):
    """Structured output — every provider translates this; none reads the
    brief for creative strategy."""

    model_config = ConfigDict(extra="forbid")

    version: str = PROMPT_VERSION
    positive_prompt: str
    negative_constraints: list[str] = Field(default_factory=list)
    reference_instructions: list[str] = Field(default_factory=list)
    composition_instructions: list[str] = Field(default_factory=list)
    output_instructions: list[str] = Field(default_factory=list)
    # The verified facts the prompt actually states, and the interpretive
    # direction it adds — kept apart so provenance can show which is which.
    verified_facts: list[str] = Field(default_factory=list)
    creative_interpretation: list[str] = Field(default_factory=list)
    # Debug/provenance only: never URLs, credentials or full business text.
    debug: dict = Field(default_factory=dict)


def _without_business_name(text: str, business_name: str) -> str:
    if not business_name.strip():
        return text
    return re.sub(re.escape(business_name), "the business", text, flags=re.IGNORECASE)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _verified_facts(brief: CreativeBrief) -> list[str]:
    """Only what the CreativeBrief states. The business name is
    deliberately left out (and scrubbed from free text): with generated
    text forbidden, naming the business invites the model to render it."""
    facts = [f"Industry: {brief.industry}."]
    if brief.description:
        description = _without_business_name(brief.description, brief.business_name)
        facts.append(f"Description: {_clip(description, _MAX_DESCRIPTION_CHARS)}")
    services = [_without_business_name(service.name, brief.business_name) for service in brief.services[:_MAX_SERVICES]]
    if services:
        facts.append("Offerings: " + "; ".join(services) + ".")
    if brief.target_customer:
        target = _without_business_name(brief.target_customer, brief.business_name)
        facts.append(f"Target customer: {_clip(target, 200)}")
    return facts


def _reference_instruction(index: int, total: int, reference: ReferenceSpec) -> str:
    label = "The supplied reference" if total == 1 else f"Reference {index}"
    if reference.source == "previous_generation":
        return (
            f"{label} is the previously generated image for this same creative direction. Keep the same world, "
            "palette and visual language."
        )
    match reference.usage:
        case ReferenceUsage.IDENTITY:
            return (
                f"{label} is the official brand logo. Use it only to understand palette, geometric language and "
                "brand character. Do not reproduce, redraw, imitate or place the logo, or any lettering from it, "
                "in the generated image."
            )
        case ReferenceUsage.PALETTE:
            return (
                f"{label} is the official brand logo. Use it only to take its colour palette. Do not reproduce its "
                "shapes or lettering and do not place the logo in the generated image."
            )
        case ReferenceUsage.PRODUCT:
            return (
                f"{label} shows the real product. Keep the product the primary subject, faithful in shape, colour "
                "and detail. Do not invent additional products or variations."
            )
        case ReferenceUsage.SUBJECT:
            return (
                f"{label} shows the real subject. Keep it recognisable and faithful; do not alter it or invent "
                "features."
            )
        case ReferenceUsage.COMPOSITION:
            return (
                f"{label} is real business imagery. Borrow only its framing and balance of elements; do not copy "
                "its subject."
            )
        case ReferenceUsage.STYLE:
            return (
                f"{label} is real business imagery. Use only its mood, lighting and material feel; do not copy "
                "its subject or composition."
            )


def _brand_identity_lines(profile: BrandVisualProfile, spec: CreativeGenerationSpec) -> list[str]:
    """Brand identity communicated as TEXT from the BrandVisualProfile — the
    logo image itself is never sent to the model (P2.3). Only what the
    profile reliably knows is stated; missing information is stated as
    missing, never assumed."""
    if spec.brand_mode is BrandStrategy.NEW_DIRECTION:
        return []
    lines: list[str] = []
    if profile.palette:
        stance = "Use" if spec.brand_mode is BrandStrategy.PRESERVE else "Start from"
        colors = ", ".join(f"{color.role} {color.value}" for color in profile.palette)
        lines.append(f"{stance} the brand palette: {colors}.")
    if profile.visual_style:
        lines.append(f"Brand visual style (from business settings): {profile.visual_style}.")
    if profile.geometry:
        lines.append("Brand geometric language: " + "; ".join(profile.geometry) + ".")
    if not lines:
        lines.append("No verified brand palette or visual style is available: do not assume one.")
    return lines


def compose_prompt(
    brief: CreativeBrief,
    spec: CreativeGenerationSpec,
    *,
    angle: str,
    continuation_of: str | None = None,
    profile: BrandVisualProfile | None = None,
) -> ComposedCreativePrompt:
    profile = profile or build_brand_visual_profile(brief, [])
    facts = _verified_facts(brief)
    role = _PURPOSE_ROLE[spec.purpose]
    level = _LEVEL_DIRECTION[spec.creative_level]

    business_lines = [*facts]
    if not brief.description and not brief.services:
        business_lines.append(
            "No further verified business details are available: rely on the industry only, "
            "and do not invent products, projects or claims."
        )

    interpretation = [
        f"Visual direction: {angle}.",
        f"Overall feel: {level}.",
        _BRAND_MODE_DIRECTION[spec.brand_mode],
    ]
    interpretation.extend(_brand_identity_lines(profile, spec))
    if continuation_of:
        interpretation.insert(
            0, f"Continue the same world and visual language as the previous exploration ({continuation_of})."
        )

    positive = (
        f"Create an original image to be used as {role}.\n"
        "BUSINESS CONTEXT (verified facts only):\n"
        + "\n".join(business_lines)
        + "\nVISUAL DIRECTION (creative interpretation, not business claims):\n"
        + "\n".join(interpretation)
    )

    reference_lines = [
        _reference_instruction(index, len(spec.reference_assets), ref)
        for index, ref in enumerate(spec.reference_assets, start=1)
    ]
    if not reference_lines:
        reference_lines = [
            "No reference images are supplied: work only from the verified context and visual direction."
        ]

    negatives: list[str] = []
    if spec.text_policy is TextPolicy.NO_GENERATED_TEXT:
        negatives.extend(_NO_TEXT_NEGATIVES)
    negatives.extend(_GENERAL_NEGATIVES)
    if spec.purpose is not AssetPurpose.TEXTURE:
        negatives.append("no duplicated or repeated subjects")
    if brief.logo_url or profile.has_official_logo:
        negatives.append(_LOGO_NEGATIVE)

    output_lines = [
        f"Aspect ratio {spec.output.aspect_ratio}; a single image.",
        "High resolution, sharp and production-ready for the web.",
        "Digital image only: no device mockup or frame.",
    ]

    return ComposedCreativePrompt(
        positive_prompt=positive,
        negative_constraints=negatives,
        reference_instructions=reference_lines,
        composition_instructions=list(_PURPOSE_COMPOSITION[spec.purpose]),
        output_instructions=output_lines,
        verified_facts=facts,
        creative_interpretation=interpretation,
        debug={
            "purpose": spec.purpose.value,
            "brand_mode": spec.brand_mode.value,
            "creative_level": spec.creative_level.value,
            "text_policy": spec.text_policy.value,
            "reference_usages": [ref.usage.value for ref in spec.reference_assets],
            "business_name_in_prompt": False,
            "brand_profile_version": profile.version,
            "brand_profile_sources": list(profile.sources),
            "angle": angle,
            "is_continuation": continuation_of is not None,
        },
    )
