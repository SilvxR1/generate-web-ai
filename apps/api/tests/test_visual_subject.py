"""VisualSubject (P2.5) — one narrow, defensible visual focus, chosen
deterministically from verified evidence. Pure domain tests."""

from app.domain.creative.creative_context import CreativeContext
from app.domain.creative.visual_intent import SubjectGrounding, VisualIntent, VisualIntentKind
from app.domain.creative.visual_subject import (
    VisualSubjectSource,
    material_family,
    select_visual_subject,
)


def _context(*labels: str) -> CreativeContext:
    return CreativeContext(subject_categories=list(labels), included_fields=["services"] if labels else [])


def _intent(kind: VisualIntentKind, grounding: SubjectGrounding = SubjectGrounding.CONCEPTUAL) -> VisualIntent:
    return VisualIntent(kind=kind, grounding=grounding, reason="test")


def _editorial(*labels: str):
    return select_visual_subject(intent=_intent(VisualIntentKind.SUBJECT_EDITORIAL), context=_context(*labels))


def test_a_subject_is_distinct_from_the_visual_intent():
    subject = _editorial("Llaveros de lana")

    assert subject.label == "crochet and yarn craft"
    assert not hasattr(subject, "kind")  # intent says WHAT KIND of visual; the subject says WHAT to focus on
    assert subject.source is VisualSubjectSource.MATERIAL_FAMILY


def test_a_grounded_product_intent_takes_its_subject_from_the_reference_not_from_labels():
    subject = select_visual_subject(
        intent=_intent(VisualIntentKind.PRODUCT_GROUNDED, SubjectGrounding.GROUNDED),
        context=_context("Llaveros de lana", "Amigurumis"),
    )

    assert subject.source is VisualSubjectSource.GROUNDED_REFERENCE
    assert subject.label is None and subject.family is None  # never substituted with a normalized category
    assert subject.grounding is SubjectGrounding.GROUNDED


def test_an_ungrounded_product_intent_stays_unknown_and_is_never_replaced_by_a_label():
    subject = select_visual_subject(
        intent=_intent(VisualIntentKind.PRODUCT_GROUNDED, SubjectGrounding.UNKNOWN),
        context=_context("Llaveros de lana"),
    )

    assert subject.label is None
    assert subject.grounding is SubjectGrounding.UNKNOWN
    assert subject.reason == "product_subject_unknown_no_real_reference"


def test_verified_labels_that_support_a_material_family_choose_that_family():
    subject = _editorial(
        "Amigurumis artesanales hechos a mano", "Llaveros de lana", "Tartas de pañales", "Cestas personalizadas"
    )

    assert subject.family == "yarn_craft" and subject.label == "crochet and yarn craft"
    assert subject.considered_categories == 4
    assert subject.reason == "verified_labels_support_a_material_family"


def test_the_family_with_the_most_supporting_labels_wins():
    subject = _editorial("Cerámica artesanal", "Lana merino", "Hilos de algodón")
    assert subject.family == "yarn_craft"

    subject = _editorial("Cerámica esmaltada", "Piezas de alfarería", "Lana")
    assert subject.family == "ceramics"


def test_matching_is_accent_insensitive_and_covers_several_families():
    assert _editorial("Cerámica").family == "ceramics"
    assert _editorial("Trabajos en madera").family == "woodcraft"
    assert _editorial("Marroquinería a medida").family == "leathercraft"


def test_no_family_is_inferred_when_labels_do_not_support_one_a_single_category_is_kept():
    subject = _editorial("Tartas de pañales", "Cestas personalizadas")

    assert subject.family is None
    assert subject.source is VisualSubjectSource.VERIFIED_CATEGORY
    assert subject.label == "Tartas de pañales"  # ONE verified category, never a mix
    assert "Cestas" not in (subject.label or "")


def test_unrelated_offerings_are_never_combined_into_one_subject():
    subject = _editorial("Tartas de pañales", "Cestas personalizadas", "Velas aromáticas")

    assert subject.label == "Tartas de pañales"
    assert ";" not in (subject.label or "")


def test_a_similar_looking_word_does_not_create_a_family():
    assert _editorial("Lanzamiento de productos").family is None  # "lanzamiento" is not "lana"


def test_a_missing_product_is_not_invented_no_labels_means_no_subject():
    subject = select_visual_subject(intent=_intent(VisualIntentKind.ATMOSPHERIC), context=_context())

    assert subject.source is VisualSubjectSource.NONE and subject.label is None and subject.family is None
    assert subject.reason == "intent_has_no_literal_subject"


def test_abstract_and_atmospheric_intents_have_no_literal_subject_even_when_labels_exist():
    for kind in (VisualIntentKind.ABSTRACT_BRAND, VisualIntentKind.ATMOSPHERIC):
        subject = select_visual_subject(intent=_intent(kind), context=_context("Llaveros de lana"))
        assert subject.source is VisualSubjectSource.NONE and subject.label is None


def test_a_subject_never_upgrades_grounding_beyond_conceptual():
    assert _editorial("Llaveros de lana").grounding is SubjectGrounding.CONCEPTUAL
    assert _editorial("Tartas de pañales").grounding is SubjectGrounding.CONCEPTUAL


def test_the_family_lexicon_describes_generic_materials_never_finished_products():
    for key in ("yarn_craft", "ceramics", "woodcraft", "leathercraft"):
        family = material_family(key)
        assert family is not None and "no identifiable finished products" in family.treatment
    assert material_family("unknown") is None and material_family(None) is None


def test_selection_is_deterministic():
    labels = ("Llaveros de lana", "Cerámica", "Madera")
    assert _editorial(*labels) == _editorial(*labels)
