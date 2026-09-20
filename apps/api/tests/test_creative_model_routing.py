"""CreativeModelRouter (P2.3) — capability-based model selection and the
verified Higgsfield capability registry. No network, no provider call."""

import pytest

from app.creative.higgsfield.api_client import (
    HiggsfieldApiUnavailableError,
    registered_models,
    resolve_model_config,
)
from app.domain.creative.model_routing import (
    NO_SUITABLE_MODEL,
    CapabilityVerification,
    CreativeGenerationRequirements,
    ModelCapabilities,
    NoSuitableModelError,
    OutputKind,
    RegisteredModel,
    select_model,
)

SOUL_REFERENCE = "higgsfield-ai/soul/reference"
SOUL_STANDARD = "higgsfield-ai/soul/standard"
NANO = "nano-banana"


def _caps(
    *,
    supports=False,
    requires=False,
    max_refs=0,
    ratios=frozenset({"16:9", "1:1"}),
    verified=CapabilityVerification.CURRENT_OFFICIAL_SPEC,
) -> ModelCapabilities:
    return ModelCapabilities(
        output=OutputKind.IMAGE,
        supports_reference=supports,
        requires_reference=requires,
        max_reference_images=max_refs,
        supported_aspect_ratios=ratios,
        reference_roles=None,
        verified_by=verified,
    )


def _model(model_id: str, caps: ModelCapabilities) -> RegisteredModel:
    return RegisteredModel(provider="test", model_id=model_id, capabilities=caps)


def _req(*, required=0, optional=0, ratio="16:9") -> CreativeGenerationRequirements:
    return CreativeGenerationRequirements(
        aspect_ratio=ratio,
        requires_visual_reference=required > 0,
        required_reference_count=required,
        optional_reference_count=optional,
    )


TEXT_ONLY = _model("text-only", _caps())
NEEDS_REF = _model("needs-ref", _caps(supports=True, requires=True, max_refs=1))
FLEX_REF = _model("flex-ref", _caps(supports=True, max_refs=8))


# --- generic router behaviour -------------------------------------------------


def test_router_selects_only_models_whose_capabilities_satisfy_the_requirements():
    selection = select_model(_req(), [NEEDS_REF, TEXT_ONLY])

    assert selection.model_id == "text-only"
    assert [r.model_id for r in selection.rejected] == ["needs-ref"]
    assert selection.rejected[0].reason == "requires_a_reference_but_none_is_wanted"


def test_a_reference_required_model_is_never_selected_for_a_no_reference_request():
    with pytest.raises(NoSuitableModelError):
        select_model(_req(), [NEEDS_REF])


def test_router_fails_safely_when_no_model_satisfies_the_requirements():
    with pytest.raises(NoSuitableModelError) as excinfo:
        select_model(_req(required=1), [TEXT_ONLY])

    assert excinfo.value.reason_code == NO_SUITABLE_MODEL
    assert [r.reason for r in excinfo.value.rejected] == ["required_reference_not_supported"]


def test_router_fails_safely_with_no_registered_models_at_all():
    with pytest.raises(NoSuitableModelError):
        select_model(_req(), [])


def test_a_required_reference_needs_a_model_that_can_take_it():
    selection = select_model(_req(required=1), [TEXT_ONLY, NEEDS_REF, FLEX_REF])
    assert selection.model_id in {"needs-ref", "flex-ref"}
    assert "text-only" in {r.model_id for r in selection.rejected}


def test_the_reference_count_must_fit_the_model_limit():
    with pytest.raises(NoSuitableModelError):
        select_model(_req(required=2), [NEEDS_REF])  # max 1


def test_the_configured_model_wins_when_it_satisfies_the_requirements():
    selection = select_model(_req(), [TEXT_ONLY, _model("other-text", _caps())], preferred_model_id="other-text")

    assert selection.model_id == "other-text"
    assert selection.reason == "configured_model_satisfies_requirements"


def test_an_unsuitable_configured_model_is_replaced_and_the_reason_is_recorded():
    selection = select_model(_req(), [NEEDS_REF, TEXT_ONLY], preferred_model_id="needs-ref")

    assert selection.model_id == "text-only"
    assert (
        selection.reason
        == "configured_model_unsuitable:requires_a_reference_but_none_is_wanted; selected_by_capability"
    )


def test_an_unsupported_aspect_ratio_rejects_a_model_only_when_its_ratios_are_known():
    unknown_ratios = _model("unknown-ratios", _caps(ratios=None))
    known_ratios = _model("known-ratios", _caps(ratios=frozenset({"1:1"})))

    selection = select_model(_req(ratio="16:9"), [known_ratios, unknown_ratios])

    assert selection.model_id == "unknown-ratios"  # unknown stays unknown, never guessed unsupported
    assert {"known-ratios": "aspect_ratio_not_supported"} == {r.model_id: r.reason for r in selection.rejected}


def test_better_verified_models_are_preferred_when_several_qualify():
    weak = _model("weak", _caps(verified=CapabilityVerification.EARLIER_OFFICIAL_SPEC))
    strong = _model("strong", _caps(verified=CapabilityVerification.CURRENT_OFFICIAL_SPEC))

    assert select_model(_req(), [weak, strong]).model_id == "strong"


def test_optional_references_prefer_a_model_that_can_use_them_and_are_dropped_otherwise():
    prefers_ref = select_model(_req(optional=1), [TEXT_ONLY, FLEX_REF])
    assert prefers_ref.model_id == "flex-ref" and prefers_ref.dropped_optional_references is False

    dropped = select_model(_req(optional=1), [TEXT_ONLY])
    assert dropped.model_id == "text-only" and dropped.dropped_optional_references is True


def test_a_reference_required_model_is_acceptable_when_optional_references_exist():
    assert select_model(_req(optional=1), [NEEDS_REF]).model_id == "needs-ref"


# --- the verified Higgsfield capability registry ------------------------------


def test_registered_higgsfield_capabilities_are_recorded_honestly():
    models = {m.model_id: m.capabilities for m in registered_models()}

    assert set(models) == {NANO, SOUL_REFERENCE, SOUL_STANDARD}
    standard, reference, nano = models[SOUL_STANDARD], models[SOUL_REFERENCE], models[NANO]

    assert (standard.supports_reference, standard.requires_reference, standard.max_reference_images) == (
        False,
        False,
        0,
    )
    assert standard.verified_by is CapabilityVerification.CURRENT_OFFICIAL_SPEC
    assert (reference.supports_reference, reference.requires_reference, reference.max_reference_images) == (
        True,
        True,
        1,
    )
    assert reference.verified_by is CapabilityVerification.OBSERVED_IN_PRODUCTION
    assert (nano.supports_reference, nano.requires_reference, nano.max_reference_images) == (True, False, 8)
    assert nano.verified_by is CapabilityVerification.EARLIER_OFFICIAL_SPEC
    assert all(m.reference_roles is None for m in models.values())  # roles are undocumented: unknown, not guessed
    assert all(m.output is OutputKind.IMAGE for m in models.values())


def test_soul_standard_matches_the_published_prompt_only_request_shape():
    config = resolve_model_config(SOUL_STANDARD)

    assert config.endpoint == "/higgsfield-ai/soul/standard"
    assert config.build_reference_payload(["https://x/y.png"]) == {}  # no reference field exists for this model
    assert config.supported_aspect_ratios >= {"16:9", "1:1", "4:3", "3:2", "21:9"}


def test_the_allowlist_still_rejects_unregistered_models():
    with pytest.raises(HiggsfieldApiUnavailableError):
        resolve_model_config("some-invented-model")


def test_a_no_reference_hero_is_never_routed_to_soul_reference_even_when_it_is_configured():
    """The exact production situation: HIGGSFIELD_API_MODEL=soul/reference and
    a HERO with no reference to send."""
    selection = select_model(_req(), registered_models(), preferred_model_id=SOUL_REFERENCE)

    assert selection.model_id == SOUL_STANDARD
    assert "configured_model_unsuitable:requires_a_reference_but_none_is_wanted" in selection.reason
    assert selection.model_id != SOUL_REFERENCE


def test_soul_reference_is_still_selected_for_a_legitimate_required_reference():
    selection = select_model(_req(required=1, ratio="1:1"), registered_models(), preferred_model_id=SOUL_REFERENCE)

    assert selection.model_id == SOUL_REFERENCE
    assert selection.reason == "configured_model_satisfies_requirements"


def test_no_registered_model_is_selected_when_only_a_reference_required_model_exists():
    only_reference = [m for m in registered_models() if m.model_id == SOUL_REFERENCE]
    with pytest.raises(NoSuitableModelError):
        select_model(_req(), only_reference, preferred_model_id=SOUL_REFERENCE)
