"""VisualSubject (P2.5) — the ONE narrow thing an image should focus on,
selected deterministically from what the business has verified.

Why: P2.4 handed the image model every verified offering at once ("represents
these verified subject categories: a; b; c; d") and the model tried to render
all of them — the labels even appeared as text inside the picture. A single
image needs a single, concrete focus.

Selection order (real evidence first, never invention):

1. GROUNDED_REFERENCE — the subject comes from a real product reference.
2. MATERIAL_FAMILY    — verified service labels support a broader, visual
                        material family ("amigurumis", "llaveros de lana" →
                        crochet and yarn craft). Only when the labels
                        themselves contain the family's stems; a family is
                        never inferred from the business type or from prose.
3. VERIFIED_CATEGORY  — otherwise a SINGLE verified category, never a mix of
                        unrelated offerings.
4. NONE               — abstract/atmospheric intents have no literal subject.

The subject is a *concept*, not inventory: SubjectGrounding stays conceptual
unless a real reference grounds it, and the scene plan represents a family with
generic materials — never an identifiable finished product presented as the
business's own.

No LLM: a small conservative lexicon of stems. It can miss a family (falling
back to a single verified category) but cannot create one that the labels do
not support.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.creative.creative_context import CreativeContext
from app.domain.creative.visual_intent import SubjectGrounding, VisualIntent, VisualIntentKind

VISUAL_SUBJECT_VERSION = "p2.5-v1"


class VisualSubjectSource(StrEnum):
    GROUNDED_REFERENCE = "grounded_reference"
    MATERIAL_FAMILY = "material_family_from_verified_labels"
    VERIFIED_CATEGORY = "single_verified_category"
    NONE = "none"


@dataclass(frozen=True)
class MaterialFamily:
    key: str
    # Short label recorded in provenance / shown in Studio.
    label: str
    # How the scene names the subject.
    scene_phrase: str
    medium: str
    treatment: str
    emphasis: str
    stems: tuple[str, ...]


_FAMILIES: tuple[MaterialFamily, ...] = (
    MaterialFamily(
        key="yarn_craft",
        label="crochet and yarn craft",
        scene_phrase="crochet and yarn craft materials",
        medium="studio still-life photograph",
        treatment=(
            "generic yarn, wool and handcrafted textile forms arranged as one tactile group, "
            "no identifiable finished products"
        ),
        emphasis="tactile textile detail and stitch texture",
        stems=("amigurumi", "crochet", "ganchillo", "lana", "hilo", "yarn", "wool", "knit", "tejid", "tricot"),
    ),
    MaterialFamily(
        key="ceramics",
        label="ceramic craft",
        scene_phrase="hand-formed ceramic craft materials",
        medium="studio still-life photograph",
        treatment="generic clay forms and glazed surfaces, no identifiable finished products",
        emphasis="clay and glaze texture",
        stems=("ceram", "alfarer", "pottery", "porcelan"),
    ),
    MaterialFamily(
        key="woodcraft",
        label="woodcraft",
        scene_phrase="woodcraft materials",
        medium="studio still-life photograph",
        treatment="generic wood grain, shavings and simple carved forms, no identifiable finished products",
        emphasis="wood grain and carved texture",
        stems=("madera", "wood", "carpinter", "ebanister"),
    ),
    MaterialFamily(
        key="leathercraft",
        label="leather craft",
        scene_phrase="leather craft materials",
        medium="studio still-life photograph",
        treatment="generic leather pieces, stitching and tools, no identifiable finished products",
        emphasis="leather grain and stitching",
        stems=("cuero", "leather", "marroquiner"),
    ),
)

_FAMILY_BY_KEY = {family.key: family for family in _FAMILIES}


def material_family(key: str | None) -> MaterialFamily | None:
    return _FAMILY_BY_KEY.get(key) if key else None


class VisualSubject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = VISUAL_SUBJECT_VERSION
    source: VisualSubjectSource
    # A concise visual label, or None when the subject is a real reference or
    # there is no literal subject.
    label: str | None = None
    # Set only for MATERIAL_FAMILY subjects.
    family: str | None = None
    grounding: SubjectGrounding
    # A code explaining the choice — provenance, never prose.
    reason: str
    # How many verified categories were available to choose from.
    considered_categories: int = 0


def _tokens(label: str) -> list[str]:
    decomposed = unicodedata.normalize("NFKD", label.lower())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", stripped)


def _supports(family: MaterialFamily, label: str) -> bool:
    return any(token.startswith(stem) for token in _tokens(label) for stem in family.stems)


def _best_family(labels: list[str]) -> MaterialFamily | None:
    best: MaterialFamily | None = None
    best_score = 0
    for family in _FAMILIES:
        score = sum(1 for label in labels if _supports(family, label))
        if score > best_score:
            best, best_score = family, score
    return best


def select_visual_subject(*, intent: VisualIntent, context: CreativeContext) -> VisualSubject:
    considered = len(context.subject_categories)
    if intent.kind is VisualIntentKind.PRODUCT_GROUNDED:
        return VisualSubject(
            source=VisualSubjectSource.GROUNDED_REFERENCE,
            grounding=intent.grounding,
            reason="subject_comes_from_the_grounded_product_reference"
            if intent.grounding is SubjectGrounding.GROUNDED
            else "product_subject_unknown_no_real_reference",
            considered_categories=considered,
        )
    if intent.kind is VisualIntentKind.SUBJECT_EDITORIAL and context.subject_categories:
        labels = list(context.subject_categories)
        family = _best_family(labels)
        if family is not None:
            return VisualSubject(
                source=VisualSubjectSource.MATERIAL_FAMILY,
                label=family.label,
                family=family.key,
                grounding=SubjectGrounding.CONCEPTUAL,
                reason="verified_labels_support_a_material_family",
                considered_categories=considered,
            )
        return VisualSubject(
            source=VisualSubjectSource.VERIFIED_CATEGORY,
            label=labels[0],
            grounding=SubjectGrounding.CONCEPTUAL,
            reason="no_material_family_supported_first_verified_category_chosen",
            considered_categories=considered,
        )
    return VisualSubject(
        source=VisualSubjectSource.NONE,
        grounding=intent.grounding,
        reason="intent_has_no_literal_subject",
        considered_categories=considered,
    )
