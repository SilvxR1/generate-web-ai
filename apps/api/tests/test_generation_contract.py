"""GenerationContract (P2.5) — the provider-independent contract and its
pre-spend validation. Pure domain tests: no network, R2, Higgsfield or DB.

Validation is structural/semantic; these tests also pin that it never claims
to be visual QA."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.business_config import BusinessConfig, BusinessProfile, ServiceOffering
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.generation_contract import (
    GenerationContract,
    InvalidGenerationContractError,
    assert_valid_generation_contract,
    validate_generation_contract,
)
from app.domain.creative.planning import GenerationPlan, plan_generation
from app.domain.creative.reference_strategy import ReferencePolicy
from app.domain.creative.spec import ReferenceSpec, ReferenceUsage
from app.domain.creative.visual_intent import SubjectGrounding
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, AssetPurpose, BusinessVertical


def _plan(purpose: AssetPurpose = AssetPurpose.HERO, assets=(), services=("Llaveros de lana",)) -> GenerationPlan:
    config = BusinessConfig(
        business_profile=BusinessProfile(
            name="Acme",
            slug="acme",
            industry=BusinessVertical.OTHER,
            services=[
                ServiceOffering(id=f"s-{i}", name=name, description="Descripcion.")
                for i, name in enumerate(services, start=1)
            ],
        )
    )
    return plan_generation(build_creative_brief(business_config=config, purpose=purpose), list(assets))


def _product() -> CreativeBriefAsset:
    return CreativeBriefAsset(
        id=uuid4(),
        kind=AssetKind.IMAGE,
        category=AssetCategory.PRODUCT,
        origin=AssetOrigin.UPLOADED,
        url="https://x/p.png",
    )


def _codes(contract: GenerationContract, **kwargs) -> set[str]:
    return {issue.code for issue in validate_generation_contract(contract, **kwargs)}


def test_the_contract_gathers_every_decision_before_any_provider_is_involved():
    plan = _plan()
    contract = plan.contract

    assert contract.purpose is AssetPurpose.HERO
    assert contract.visual_intent.value == "subject_editorial"
    assert contract.subject.label == "crochet and yarn craft"
    assert contract.grounding is SubjectGrounding.CONCEPTUAL
    assert contract.scene == plan.scenes[0]
    assert contract.text_policy.value == "no_generated_text"
    assert contract.interface_policy.value == "no_interface_depiction"
    assert contract.reference_policy is ReferencePolicy.NO_VISUAL_REFERENCE and contract.provider_references == ()
    assert contract.output.aspect_ratio == "16:9" and contract.output.num_outputs == 1
    dumped = contract.model_dump_json().lower()
    assert "higgsfield" not in dumped and "soul" not in dumped  # provider/model details are absent by design


def test_a_valid_hero_contract_passes_for_every_variant():
    plan = _plan()
    for variant in range(3):
        assert validate_generation_contract(plan.contract_for(variant)) == []
    assert_valid_generation_contract(plan.contract)  # does not raise


def test_a_product_purpose_without_a_grounded_reference_is_invalid():
    plan = _plan(AssetPurpose.PRODUCT)

    codes = _codes(plan.contract)

    assert "product_requires_grounded_reference" in codes
    assert "fidelity_requires_grounded_reference" in codes  # the scene itself needs fidelity too
    assert "required_reference_missing" in codes


def test_a_grounded_product_contract_is_valid_once_the_real_reference_is_selected():
    plan = _plan(AssetPurpose.PRODUCT, assets=[_product()])
    contract = plan.contract_for(0, plan.spec.reference_assets)

    assert contract.grounding is SubjectGrounding.GROUNDED and contract.provider_references
    assert validate_generation_contract(contract) == []


def test_a_grounded_product_whose_reference_was_not_resolved_is_invalid_before_spend():
    plan = _plan(AssetPurpose.PRODUCT, assets=[_product()])

    assert "required_reference_missing" in _codes(plan.contract_for(0, []))


def test_a_scene_that_needs_fidelity_but_is_only_conceptual_is_invalid():
    plan = _plan()
    contract = plan.contract.with_scene(plan.contract.scene.model_copy(update={"requires_fidelity": True}))

    assert "fidelity_requires_grounded_reference" in _codes(contract)


def test_a_hero_scene_that_asks_for_a_webpage_or_interface_is_invalid():
    plan = _plan()
    for primary in ("a website landing page", "a browser window", "an app screen", "a navigation menu"):
        contract = plan.contract.with_scene(plan.contract.scene.model_copy(update={"primary_subject": primary}))
        assert "scene_requests_interface" in _codes(contract), primary


def test_a_scene_that_requires_text_conflicts_with_no_generated_text():
    plan = _plan()
    for primary in ("a bold headline text", "a sign with lettering", "a logo lockup", "a caption"):
        contract = plan.contract.with_scene(plan.contract.scene.model_copy(update={"primary_subject": primary}))
        assert "scene_requests_text" in _codes(contract), primary


def test_ordinary_words_that_merely_contain_text_or_sign_do_not_trip_the_scene_checks():
    plan = _plan()
    scene = plan.contract.scene.model_copy(
        update={"primary_subject": "textile design samples", "environment": "a signature warm tone"}
    )
    assert _codes(plan.contract.with_scene(scene)) == set()


def test_a_reference_policy_that_forbids_references_conflicts_with_a_selected_reference():
    plan = _plan()
    contract = plan.contract.with_provider_references([ReferenceSpec(asset_id=uuid4(), usage=ReferenceUsage.STYLE)])

    assert "reference_policy_conflict" in _codes(contract)


def test_a_brand_mark_can_never_be_a_provider_reference():
    plan = _plan()
    for usage in (ReferenceUsage.IDENTITY, ReferenceUsage.PALETTE):
        contract = plan.contract.with_provider_references([ReferenceSpec(asset_id=uuid4(), usage=usage)])
        assert "brand_mark_as_provider_reference" in _codes(contract)


def test_an_aspect_ratio_no_candidate_model_supports_is_invalid_but_unknown_support_is_not():
    contract = _plan().contract  # 16:9

    assert "aspect_ratio_unsupported_by_all_models" in _codes(
        contract, candidate_aspect_ratios=[frozenset({"1:1"}), frozenset({"4:3"})]
    )
    assert _codes(contract, candidate_aspect_ratios=[frozenset({"1:1"}), frozenset({"16:9"})]) == set()
    assert _codes(contract, candidate_aspect_ratios=[frozenset({"1:1"}), None]) == set()  # unknown stays unknown


def test_assert_valid_raises_with_the_first_issue_as_the_reason_code_and_lists_every_issue():
    contract = _plan(AssetPurpose.PRODUCT).contract

    with pytest.raises(InvalidGenerationContractError) as excinfo:
        assert_valid_generation_contract(contract)

    assert excinfo.value.reason_code == "product_requires_grounded_reference"
    assert len(excinfo.value.issues) >= 3


def test_the_contract_is_immutable_and_derived_copies_do_not_change_the_original():
    plan = _plan()
    with pytest.raises(ValidationError):
        plan.contract.purpose = AssetPurpose.BACKGROUND  # type: ignore[misc]

    derived = plan.contract.with_provider_references([ReferenceSpec(asset_id=uuid4(), usage=ReferenceUsage.STYLE)])
    assert derived.provider_references and plan.contract.provider_references == ()


def test_validation_is_not_visual_qa_and_makes_no_claim_about_the_generated_image():
    assert "Pure" in (validate_generation_contract.__doc__ or "")
    assert not hasattr(GenerationContract, "visual_qa")  # nothing here inspects pixels
