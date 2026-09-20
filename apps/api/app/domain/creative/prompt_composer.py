"""CreativePromptComposer (P2.2, restructured in P2.4) — turns a CreativeBrief,
a CreativeGenerationSpec and the P2.4 CreativeContext / VisualIntent into a
structured, provider-independent ComposedCreativePrompt. Pure and
deterministic: no network, R2, provider SDK or database.

The prompt is built from ten explicit sections, so each concern is separate
and testable:

  1. OUTPUT CONTRACT      what kind of asset this is (a standalone picture)
  2. PLACEMENT            where it will LATER be used (not what it depicts)
  3. VISUAL INTENT        what kind of image to create
  4. VERIFIED CONTEXT     only relevant, verified, visually useful facts
  5. BRAND VISUAL PROFILE only structured brand information that exists
  6. COMPOSITION          placement-specific framing and crop rules
  7. SUBJECT TRUTH        conceptual vs. grounded in a real subject
  8. TEXT POLICY          no generated text of any kind
  9. INTERFACE POLICY     never a website / browser / app / UI
 10. OUTPUT REQUIREMENTS  aspect ratio, resolution

plus reference instructions and negative constraints. Raw business
descriptions are never included: business knowledge arrives only through
CreativeContext.

HERO means "this picture will later sit inside a website hero" — it does NOT
mean "generate a website hero section" (Experiment 3 drew a webpage mockup).
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brand_profile import BrandVisualProfile, build_brand_visual_profile
from app.domain.creative.brief import CreativeBrief
from app.domain.creative.content_policy import interface_rules, text_rules
from app.domain.creative.creative_context import CreativeContext, build_creative_context
from app.domain.creative.spec import (
    PROMPT_VERSION,
    CreativeGenerationSpec,
    ReferenceSpec,
    ReferenceUsage,
)
from app.domain.creative.visual_intent import (
    SubjectGrounding,
    VisualIntent,
    VisualIntentKind,
    resolve_visual_intent,
)
from app.domain.enums import AssetPurpose, BrandStrategy, CreativeLevel

# Variations for abstract / atmospheric intents.
EXPLORATION_ANGLES: tuple[str, ...] = (
    "a bespoke visual metaphor drawn from the craft or product itself, expressed through abstract shape, "
    "texture and light",
    "an atmospheric, immersive scene that evokes the feeling of the business's world without depicting any "
    "specific product, person or place",
    "a calm, confident composition with clear visual hierarchy and restrained detail",
)

# Variations for a category-level subject depiction: each stays a still life
# or lifestyle-style picture in a simple setting — never an invented venue.
SUBJECT_ANGLES: tuple[str, ...] = (
    "a close, tactile still life of the subject categories in soft natural light",
    "a lifestyle-style arrangement of the subject categories in a simple, neutral setting",
    "an overhead flat-lay arrangement of the subject categories with generous space around them",
)

DEVELOP_ANGLES: tuple[str, ...] = (
    "the same world, composed so it also holds up when cropped to a narrow portrait format",
    "the same world, as a close, tactile detail of its texture and material",
    "the same world, as a calmer, wider variant with even more open negative space",
)


def exploration_angles_for(intent: VisualIntent) -> tuple[str, ...]:
    return SUBJECT_ANGLES if intent.kind is VisualIntentKind.SUBJECT_EDITORIAL else EXPLORATION_ANGLES


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

# WHERE the asset will later be used. Deliberately a placement, never a subject.
_PLACEMENT: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "a website hero section",
    AssetPurpose.SECTION: "a content section of a website",
    AssetPurpose.BACKGROUND: "a full-width background behind website content",
    AssetPurpose.PRODUCT: "a product area of a website",
    AssetPurpose.EDITORIAL: "an editorial section of a website",
    AssetPurpose.TEXTURE: "a supporting texture surface within a website",
}

_PURPOSE_COMPOSITION: dict[AssetPurpose, tuple[str, ...]] = {
    AssetPurpose.HERO: (
        "Landscape composition with one strong focal element and a clear focal hierarchy.",
        "Reserve generous negative space (about a third of the frame, on one side): calm and free of detail, so the "
        "picture can later sit beneath other page content.",
        "Keep important content away from the edges so the image survives responsive cropping.",
        "Visually distinctive, with cohesive lighting and moderate visual density.",
    ),
    AssetPurpose.BACKGROUND: (
        "Low visual density with soft gradations and a wide format.",
        "No central subject: keep the middle calm and place any interest toward the periphery.",
        "Provide clearly lighter and darker zones with enough contrast for content to sit on top later.",
        "Crop-friendly: nothing critical near the edges; it must tolerate being scaled and cropped.",
    ),
    AssetPurpose.SECTION: (
        "Supports a single content section and stays secondary in hierarchy to the hero: calmer and less dramatic.",
        "A clear but modest focal element with balanced framing and margin around it.",
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
        "Natural depth and room to breathe.",
    ),
    AssetPurpose.TEXTURE: (
        "A seamless, abstract, supporting surface: continuous or repeating pattern with no focal subject.",
        "Even density from edge to edge, with no recognisable objects, logos or marks.",
    ),
}

_GENERAL_NEGATIVES: tuple[str, ...] = (
    "no invented business claims, prices or offers",
    "no invented products, projects, people or testimonials",
    "no malformed or distorted geometry",
)

_LOGO_NEGATIVE = "do not recreate, redraw or approximate the official logo"

_NO_LITERAL_SUBJECT = "It has no literal subject: no products, people, places or objects."


class ComposedCreativePrompt(BaseModel):
    """Structured output — every provider translates this; none reads the
    brief for creative strategy."""

    model_config = ConfigDict(extra="forbid")

    version: str = PROMPT_VERSION
    output_contract: list[str] = Field(default_factory=list)
    placement: list[str] = Field(default_factory=list)
    visual_intent: list[str] = Field(default_factory=list)
    creative_context: list[str] = Field(default_factory=list)
    brand_profile: list[str] = Field(default_factory=list)
    composition_instructions: list[str] = Field(default_factory=list)
    subject_truth: list[str] = Field(default_factory=list)
    text_policy: list[str] = Field(default_factory=list)
    interface_policy: list[str] = Field(default_factory=list)
    reference_instructions: list[str] = Field(default_factory=list)
    output_instructions: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    # The affirmative core (contract + placement + intent) as one block.
    positive_prompt: str = ""
    # The verified facts the prompt actually states, and the interpretive
    # direction it adds — kept apart so provenance can show which is which.
    verified_facts: list[str] = Field(default_factory=list)
    creative_interpretation: list[str] = Field(default_factory=list)
    # Debug/provenance only: never URLs, credentials or full business text.
    debug: dict = Field(default_factory=dict)


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
    lines = [_BRAND_MODE_DIRECTION[spec.brand_mode]]
    if spec.brand_mode is BrandStrategy.NEW_DIRECTION:
        return lines
    found = False
    if profile.palette:
        stance = "Use" if spec.brand_mode is BrandStrategy.PRESERVE else "Start from"
        colors = ", ".join(f"{color.role} {color.value}" for color in profile.palette)
        lines.append(f"{stance} the brand palette: {colors}.")
        found = True
    if profile.visual_style:
        lines.append(f"Brand visual style (from business settings): {profile.visual_style}.")
        found = True
    if profile.geometry:
        lines.append("Brand geometric language: " + "; ".join(profile.geometry) + ".")
        found = True
    if not found:
        lines.append("No verified brand palette or visual style is available: do not assume one.")
    return lines


def _intent_lines(intent: VisualIntent) -> list[str]:
    match intent.kind:
        case VisualIntentKind.SUBJECT_EDITORIAL:
            return [
                "Create an editorial, still-life or lifestyle-style image that represents these verified subject "
                "categories: " + "; ".join(intent.subject_categories) + ".",
                "It is a conceptual, category-level depiction — not a documentary photograph of specific real "
                "products.",
            ]
        case VisualIntentKind.ABSTRACT_BRAND:
            return [
                "Create an abstract image built from shape, texture and light that expresses the brand's colours "
                "and style.",
                _NO_LITERAL_SUBJECT,
            ]
        case VisualIntentKind.ATMOSPHERIC:
            return [
                "Create an atmospheric image that conveys mood through light, colour and space.",
                _NO_LITERAL_SUBJECT,
            ]
        case VisualIntentKind.PRODUCT_GROUNDED:
            if intent.grounding is SubjectGrounding.GROUNDED:
                return ["Depict the real product shown in the supplied reference as the primary subject."]
            return ["The product subject is unknown: do not invent one."]


def _context_lines(context: CreativeContext) -> list[str]:
    lines: list[str] = []
    if context.business_category:
        lines.append(f"Business type: {context.business_category}.")
    if context.subject_categories:
        lines.append("Verified subject categories: " + "; ".join(context.subject_categories) + ".")
    else:
        lines.append(
            "No verified subject information is available: do not depict specific products, projects, people or "
            "premises."
        )
    lines.append("Nothing else about the business is verified for imagery: do not invent details or claims.")
    return lines


def _subject_truth_lines(intent: VisualIntent) -> list[str]:
    if intent.grounding is SubjectGrounding.GROUNDED:
        return ["The subject is grounded in the supplied real reference: keep it faithful and add nothing invented."]
    lines = [
        "This image is conceptual and representational. It must not be presented as, or imply, a real product, "
        "project, customer or premises of the business."
    ]
    if intent.grounding is SubjectGrounding.UNKNOWN:
        lines.append("The required subject information is unknown: do not invent it.")
    return lines


def compose_prompt(
    brief: CreativeBrief,
    spec: CreativeGenerationSpec,
    *,
    angle: str,
    continuation_of: str | None = None,
    profile: BrandVisualProfile | None = None,
    context: CreativeContext | None = None,
    intent: VisualIntent | None = None,
) -> ComposedCreativePrompt:
    profile = profile or build_brand_visual_profile(brief, [])
    context = context or build_creative_context(brief)
    intent = intent or resolve_visual_intent(
        purpose=spec.purpose, brand_mode=spec.brand_mode, context=context, profile=profile, assets=[]
    )
    text = text_rules(spec.text_policy)
    interface = interface_rules(spec.interface_policy)

    output_contract = [
        "Create one standalone visual asset: a single picture (photographic or illustrative). It is an image to be "
        "used later — not a page, screen or interface design."
    ]
    placement = [
        f"This asset will later be placed inside {_PLACEMENT[spec.purpose]} by the website builder.",
        "The image is only the picture that will be placed there; it is not that page.",
    ]
    visual_intent = [
        *_intent_lines(intent),
        f"Variation: {angle}.",
        f"Overall feel: {_LEVEL_DIRECTION[spec.creative_level]}.",
    ]
    if continuation_of:
        visual_intent.insert(
            0, f"Continue the same world and visual language as the previous exploration ({continuation_of})."
        )
    context_lines = _context_lines(context)
    brand_lines = _brand_identity_lines(profile, spec)

    reference_lines = [
        _reference_instruction(index, len(spec.reference_assets), ref)
        for index, ref in enumerate(spec.reference_assets, start=1)
    ]
    if not reference_lines:
        reference_lines = [
            "No reference images are supplied: work only from the verified context and visual direction."
        ]

    negatives: list[str] = [*text.negatives, *interface.negatives, *_GENERAL_NEGATIVES]
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
        output_contract=output_contract,
        placement=placement,
        visual_intent=visual_intent,
        creative_context=context_lines,
        brand_profile=brand_lines,
        composition_instructions=list(_PURPOSE_COMPOSITION[spec.purpose]),
        subject_truth=_subject_truth_lines(intent),
        text_policy=list(text.instructions),
        interface_policy=list(interface.instructions),
        reference_instructions=reference_lines,
        output_instructions=output_lines,
        negative_constraints=negatives,
        positive_prompt="\n".join([*output_contract, *placement, *visual_intent]),
        verified_facts=[line for line in context_lines if line.startswith(("Business type", "Verified subject"))],
        creative_interpretation=[*visual_intent, *brand_lines],
        debug={
            "purpose": spec.purpose.value,
            "brand_mode": spec.brand_mode.value,
            "creative_level": spec.creative_level.value,
            "text_policy": spec.text_policy.value,
            "interface_policy": spec.interface_policy.value,
            "visual_intent": intent.kind.value,
            "subject_grounding": intent.grounding.value,
            "reference_usages": [ref.usage.value for ref in spec.reference_assets],
            "business_name_in_prompt": False,
            "raw_business_description_in_prompt": False,
            "creative_context_version": context.version,
            "brand_profile_version": profile.version,
            "brand_profile_sources": list(profile.sources),
            "angle": angle,
            "is_continuation": continuation_of is not None,
        },
    )
