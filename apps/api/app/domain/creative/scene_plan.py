"""VisualScenePlan (P2.5) — HOW a subject is actually depicted: the concrete,
structured scene an image generator renders.

Between `VisualIntent` (what broad kind of visual) and the provider prompt
there used to be nothing concrete. `subject_editorial` is domain metadata,
not a scene: the model still had to invent the subject, environment,
composition, framing, lighting, layout and amount of negative space — and in
real experiments it invented a webpage. A scene plan removes that freedom.

Every field here changes what the generator is asked to draw; nothing is
speculative. The plan is:

- PROVIDER-INDEPENDENT and deterministic (no LLM, no image analysis);
- PLACEMENT-AWARE without web vocabulary: `AssetPurpose.HERO` becomes visual
  composition (wide frame, one focal area, subject biased to one side,
  generous clean negative space, crop-safe detail) — the provider is never
  told about websites, only how the picture is composed;
- HONEST about grounding: a conceptual scene uses generic materials and
  never an identifiable finished product presented as the business's own.
  Anything that needs exact product fidelity sets `requires_fidelity` and
  therefore requires a grounded real reference (checked by the contract).

Three deterministic variants (different subject side / framing) replace the
old free-text exploration angles.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.creative.brand_profile import BrandVisualProfile, PaletteSource
from app.domain.creative.visual_intent import SubjectGrounding, VisualIntent, VisualIntentKind
from app.domain.creative.visual_subject import VisualSubject, material_family
from app.domain.enums import AssetPurpose, BrandStrategy, CreativeLevel

SCENE_PLAN_VERSION = "p2.6-v1"
SCENE_VARIANTS = 3


class SubjectSide(StrEnum):
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"
    NONE = "none"


class VisualScenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = SCENE_PLAN_VERSION
    medium: str
    primary_subject: str | None
    subject_treatment: str
    environment: str
    composition: str
    subject_side: SubjectSide
    placement: str
    negative_space: str
    framing: str
    lighting: str
    depth: str
    material_emphasis: str | None
    brand_guidance: str | None
    # P2.6: the colors (hex or configured notation) that reached the scene as
    # brand styling. Empty when the brand supplies none. Never affects subject.
    brand_palette: tuple[str, ...] = ()
    aspect_ratio: str
    safe_area: str
    grounding: SubjectGrounding
    # True when the scene needs exact product fidelity — only satisfiable by a
    # grounded real reference (enforced by the generation contract).
    requires_fidelity: bool
    # Scene elements that naturally invite text or interface layouts.
    forbidden_elements: tuple[str, ...]


_FORBIDDEN_ELEMENTS: tuple[str, ...] = (
    "collage",
    "grid",
    "multi-panel layout",
    "shelves or storefront",
    "packaging",
    "product display",
)

# Composition by placement — visual language only.
_BASE_SIDE: dict[AssetPurpose, SubjectSide] = {
    AssetPurpose.HERO: SubjectSide.RIGHT,
    AssetPurpose.SECTION: SubjectSide.CENTER,
    AssetPurpose.EDITORIAL: SubjectSide.LEFT,
    AssetPurpose.PRODUCT: SubjectSide.CENTER,
    AssetPurpose.BACKGROUND: SubjectSide.NONE,
    AssetPurpose.TEXTURE: SubjectSide.NONE,
}

_COMPOSITION: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "Single continuous scene, not a collage",
    AssetPurpose.SECTION: "Single scene with a calm, even margin",
    AssetPurpose.EDITORIAL: "Single editorial scene with a clear focal path",
    AssetPurpose.PRODUCT: "A single product, fully in frame, straight-on",
    AssetPurpose.BACKGROUND: "Single continuous surface with low detail density",
    AssetPurpose.TEXTURE: "Seamless continuous surface with even density",
}

_SAFE_AREA: dict[AssetPurpose, str] = {
    AssetPurpose.HERO: "Key detail kept away from the frame edges so the image tolerates cropping",
    AssetPurpose.SECTION: "Key detail kept away from the frame edges so the image tolerates cropping",
    AssetPurpose.EDITORIAL: "Key detail kept away from the frame edges so the image tolerates cropping",
    AssetPurpose.BACKGROUND: "Nothing critical near the edges, tolerant of scaling and cropping",
    AssetPurpose.PRODUCT: "The product fully inside the frame with an even margin",
    AssetPurpose.TEXTURE: "Continuous to every edge",
}

_SIDE_PHRASES: dict[SubjectSide, tuple[str, str]] = {
    SubjectSide.RIGHT: (
        "Subject concentrated toward the right half of the frame",
        "Generous uncluttered negative space on the left",
    ),
    SubjectSide.LEFT: (
        "Subject concentrated toward the left half of the frame",
        "Generous uncluttered negative space on the right",
    ),
    SubjectSide.CENTER: ("Subject centred with an even margin around it", "Even, uncluttered space around the subject"),
    SubjectSide.NONE: ("No dominant subject; interest spread softly and evenly", "Large calm areas with low detail"),
}

_FRAMING_VARIANTS: dict[str, tuple[str, ...]] = {
    "subject": ("Medium close-up", "Overhead view", "Low-angle close-up"),
    "surface": ("Soft wide view", "Closer detail view", "Softly abstracted view"),
    "product": ("Straight-on, subject fully in frame", "Slightly elevated three-quarter view", "Close crop on detail"),
}

_ASPECT_PHRASES = {"16:9": "Wide 16:9 composition", "1:1": "Square 1:1 composition"}


def _mirror(side: SubjectSide) -> SubjectSide:
    return {SubjectSide.LEFT: SubjectSide.RIGHT, SubjectSide.RIGHT: SubjectSide.LEFT}.get(side, side)


def _lighting(kind: VisualIntentKind, level: CreativeLevel) -> str:
    literal = kind in (VisualIntentKind.SUBJECT_EDITORIAL, VisualIntentKind.PRODUCT_GROUNDED)
    if level is CreativeLevel.CINEMATIC:
        return "Dramatic low-key directional light with deep, soft shadows" if literal else "Dramatic, moody light"
    if level is CreativeLevel.PREMIUM:
        return "Soft directional studio light with gentle shadows" if literal else "Soft glowing light"
    return "Soft natural studio light" if literal else "Soft diffused light"


def _depth(kind: VisualIntentKind) -> str:
    return {
        VisualIntentKind.SUBJECT_EDITORIAL: "Shallow depth of field with a clear focal hierarchy",
        VisualIntentKind.PRODUCT_GROUNDED: "Sharp focus across the whole product",
        VisualIntentKind.ABSTRACT_BRAND: "Layered depth with one clear focal area",
        VisualIntentKind.ATMOSPHERIC: "Gentle depth with a single focal area",
    }[kind]


# Concise on purpose: a few measured colors, not a palette report.
_MAX_MEASURED_COLORS_IN_SCENE = 4


def _brand_guidance(profile: BrandVisualProfile, brand_mode: BrandStrategy) -> tuple[str | None, tuple[str, ...]]:
    """(guidance sentence, palette values). Only what the brand profile
    reliably holds; a NEW_DIRECTION is not constrained by it. Nothing is
    inferred (no logo analysis). Brand styling only — the subject is chosen
    elsewhere and is never affected."""
    if brand_mode is BrandStrategy.NEW_DIRECTION:
        return None, ()
    # PRESERVE stays faithful to the configured identity; EVOLVE only starts
    # from it. Nothing is stated when the profile holds nothing.
    stance = "use exactly" if brand_mode is BrandStrategy.PRESERVE else "start from"
    parts: list[str] = []
    palette_values: tuple[str, ...] = ()
    configured = [color for color in profile.palette if color.source is PaletteSource.BRAND_CONFIG]
    measured = [color for color in profile.palette if color.source is PaletteSource.ASSET_EXTRACTION]
    if configured:
        colors = ", ".join(f"{color.role} {color.value}" for color in configured)
        parts.append(f"{stance} this colour palette: {colors}")
        palette_values = tuple(color.value for color in configured)
    elif measured:
        # Measured (not configured) colors are guidance for harmony, so they
        # are phrased as a restrained palette rather than "use exactly".
        palette_values = tuple(color.value for color in measured[:_MAX_MEASURED_COLORS_IN_SCENE])
        lead = (
            "restrained palette derived from the brand colours"
            if brand_mode is BrandStrategy.PRESERVE
            else "palette that starts from the brand colours"
        )
        parts.append(f"{lead}: {', '.join(palette_values)}")
    if profile.visual_style:
        parts.append(f"{stance} this visual style: {profile.visual_style}")
    return ("; ".join(parts) if parts else None), palette_values


def _depiction(intent: VisualIntent, subject: VisualSubject) -> tuple[str, str | None, str, str, str | None, bool]:
    """medium, primary subject, treatment, environment, emphasis, needs fidelity."""
    match intent.kind:
        case VisualIntentKind.SUBJECT_EDITORIAL:
            family = material_family(subject.family)
            if family is not None:
                return (
                    family.medium,
                    family.scene_phrase,
                    family.treatment,
                    "Clean neutral seamless background",
                    family.emphasis,
                    False,
                )
            return (
                "Editorial photograph",
                subject.label,
                "One simple arrangement representing this category, no identifiable finished products",
                "Clean neutral seamless background",
                None,
                False,
            )
        case VisualIntentKind.ABSTRACT_BRAND:
            return (
                "Abstract composition of shape, texture and light",
                None,
                "Smooth organic forms and layered texture, no literal objects",
                "Soft gradient field",
                "layered texture",
                False,
            )
        case VisualIntentKind.ATMOSPHERIC:
            return (
                "Atmospheric photograph of light and space",
                None,
                "Soft light falling across a calm empty space, no literal subject",
                "Quiet neutral space",
                None,
                False,
            )
        case VisualIntentKind.PRODUCT_GROUNDED:
            return (
                "Clean product photograph",
                "the product shown in the reference",
                "Faithful to the reference, nothing added",
                "Clean neutral background",
                None,
                True,
            )


def plan_scene(
    *,
    purpose: AssetPurpose,
    intent: VisualIntent,
    subject: VisualSubject,
    profile: BrandVisualProfile,
    brand_mode: BrandStrategy,
    creative_level: CreativeLevel,
    aspect_ratio: str,
    variant: int = 0,
) -> VisualScenePlan:
    medium, primary, treatment, environment, emphasis, fidelity = _depiction(intent, subject)
    base_side = _BASE_SIDE[purpose]
    side = _mirror(base_side) if variant % SCENE_VARIANTS == 1 else base_side
    placement, negative_space = _SIDE_PHRASES[side]

    if intent.kind is VisualIntentKind.PRODUCT_GROUNDED:
        framing_key = "product"
    elif primary is None or purpose in (AssetPurpose.BACKGROUND, AssetPurpose.TEXTURE):
        framing_key = "surface"
    else:
        framing_key = "subject"

    brand_guidance, brand_palette = _brand_guidance(profile, brand_mode)

    return VisualScenePlan(
        medium=medium,
        primary_subject=primary,
        subject_treatment=treatment,
        environment=environment,
        composition=_COMPOSITION[purpose],
        subject_side=side,
        placement=placement,
        negative_space=negative_space,
        framing=_FRAMING_VARIANTS[framing_key][variant % SCENE_VARIANTS],
        lighting=_lighting(intent.kind, creative_level),
        depth=_depth(intent.kind),
        material_emphasis=emphasis,
        brand_guidance=brand_guidance,
        brand_palette=brand_palette,
        aspect_ratio=aspect_ratio,
        safe_area=_SAFE_AREA[purpose],
        grounding=intent.grounding,
        requires_fidelity=fidelity,
        forbidden_elements=_FORBIDDEN_ELEMENTS,
    )


def plan_scenes(
    *,
    purpose: AssetPurpose,
    intent: VisualIntent,
    subject: VisualSubject,
    profile: BrandVisualProfile,
    brand_mode: BrandStrategy,
    creative_level: CreativeLevel,
    aspect_ratio: str,
) -> tuple[VisualScenePlan, ...]:
    return tuple(
        plan_scene(
            purpose=purpose,
            intent=intent,
            subject=subject,
            profile=profile,
            brand_mode=brand_mode,
            creative_level=creative_level,
            aspect_ratio=aspect_ratio,
            variant=variant,
        )
        for variant in range(SCENE_VARIANTS)
    )


def aspect_phrase(aspect_ratio: str) -> str:
    return _ASPECT_PHRASES.get(aspect_ratio, f"{aspect_ratio} composition")
