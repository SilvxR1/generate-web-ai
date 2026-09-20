"""Metadata asset validation and provenance (P2.2).

Validation is metadata-only by design: these tests also pin that it never
claims to have checked what it cannot (text, logo distortion, brand
drift, composition, artifacts)."""

import json
from uuid import uuid4

from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.creative.asset_validation import (
    NOT_COVERED_BY_METADATA_VALIDATION,
    GeneratedAssetInfo,
    MetadataAssetValidator,
    ValidationStatus,
)
from app.domain.creative.brief import CreativeBriefAsset, build_creative_brief
from app.domain.creative.planning import plan_generation
from app.domain.creative.prompt_composer import EXPLORATION_ANGLES, compose_prompt
from app.domain.creative.provenance import COST_SEMANTICS, build_creative_provenance
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BusinessVertical

_VALIDATOR = MetadataAssetValidator()


def _spec():
    config = BusinessConfig(business_profile=BusinessProfile(name="Acme", slug="acme", industry=BusinessVertical.OTHER))
    brief = build_creative_brief(business_config=config)
    logo = CreativeBriefAsset(
        id=uuid4(),
        kind=AssetKind.LOGO,
        category=AssetCategory.LOGO,
        origin=AssetOrigin.UPLOADED,
        url="https://cdn.example.com/logo.png",
    )
    return brief, plan_generation(brief, [logo]).spec, logo


def _good(**overrides) -> GeneratedAssetInfo:
    fields = {
        "provider_completed": True,
        "result_urls": ["https://cdn.example.com/out.png"],
        "job_id": "job-1",
        "model": "higgsfield-ai/soul/reference",
    }
    fields.update(overrides)
    return GeneratedAssetInfo(**fields)


def _check(result, name):
    return next(check for check in result.checks if check.name == name)


def test_a_complete_result_passes_every_evaluable_check():
    _, spec, _ = _spec()

    result = _VALIDATOR.validate(spec, _good())

    assert result.status is ValidationStatus.PASSED
    assert all(check.passed is not False for check in result.checks)
    assert _check(result, "aspect_ratio").passed is None  # no dimensions reported: skipped, not faked


def test_missing_result_fails():
    _, spec, _ = _spec()

    result = _VALIDATOR.validate(spec, _good(result_urls=[]))

    assert result.status is ValidationStatus.FAILED
    assert _check(result, "result_exists").passed is False
    assert _check(result, "expected_output_count").passed is False


def test_incomplete_provider_status_fails():
    _, spec, _ = _spec()
    assert _VALIDATOR.validate(spec, _good(provider_completed=False)).status is ValidationStatus.FAILED


def test_non_https_result_reference_fails():
    _, spec, _ = _spec()
    result = _VALIDATOR.validate(spec, _good(result_urls=["http://cdn.example.com/out.png"]))
    assert _check(result, "result_url_valid").passed is False


def test_unexpected_media_type_fails_but_jpeg_and_webp_are_accepted():
    _, spec, _ = _spec()

    assert (
        _check(_VALIDATOR.validate(spec, _good(result_urls=["https://x/out.gif"])), "expected_media_type").passed
        is False
    )
    for accepted in ("out.jpeg", "out.jpg", "out.webp", "out.PNG"):
        result = _VALIDATOR.validate(spec, _good(result_urls=[f"https://x/{accepted}"]))
        assert _check(result, "expected_media_type").passed is True


def test_an_underivable_media_type_is_skipped_not_failed():
    _, spec, _ = _spec()

    result = _VALIDATOR.validate(spec, _good(result_urls=["https://x/download/abc123"]))

    assert _check(result, "expected_media_type").passed is None
    assert result.status is ValidationStatus.PASSED


def test_unexpected_output_count_fails():
    _, spec, _ = _spec()
    result = _VALIDATOR.validate(spec, _good(result_urls=["https://x/1.png", "https://x/2.png"]))
    assert _check(result, "expected_output_count").passed is False


def test_reported_dimensions_are_checked_against_the_requested_aspect_ratio():
    _, spec, _ = _spec()  # HERO -> 16:9

    ok = _VALIDATOR.validate(spec, _good(width=1696, height=960))
    wrong = _VALIDATOR.validate(spec, _good(width=1000, height=1000))

    assert _check(ok, "aspect_ratio").passed is True
    assert _check(wrong, "aspect_ratio").passed is False
    assert wrong.status is ValidationStatus.FAILED


def test_missing_job_or_model_identity_fails_the_provenance_check():
    _, spec, _ = _spec()
    result = _VALIDATOR.validate(spec, _good(job_id=None))
    assert _check(result, "provider_identity_recorded").passed is False


def test_validation_never_claims_visual_qa_and_lists_what_it_cannot_detect():
    _, spec, _ = _spec()

    result = _VALIDATOR.validate(spec, _good())

    assert result.visual_qa == "not_performed"
    assert set(result.not_covered) == set(NOT_COVERED_BY_METADATA_VALIDATION)
    assert {"unwanted_text", "logo_distortion", "brand_drift"} <= set(result.not_covered)


def test_provenance_records_asset_ids_and_semantics_but_no_urls_or_secrets():
    brief, spec, logo = _spec()
    composed = compose_prompt(brief, spec, angle=EXPLORATION_ANGLES[0])
    validation = _VALIDATOR.validate(spec, _good())

    provenance = build_creative_provenance(
        spec=spec,
        composed=composed,
        validation=validation,
        provider="higgsfield",
        model="higgsfield-ai/soul/reference",
        job_id="job-1",
        estimated_generation_units=2.0,
        angle=EXPLORATION_ANGLES[0],
        plan=plan_generation(brief, [logo]),
    )
    serialized = json.dumps(provenance)

    # The logo informed the brand profile but was NOT sent to the provider.
    assert provenance["brand_source_asset_ids"] == [str(logo.id)]
    assert provenance["provider_reference_asset_ids"] == []
    assert provenance["references"] == []
    assert provenance["reference_strategy"]["policy"] == "no_visual_reference"
    assert provenance["reference_strategy"]["withheld"] == [
        {"asset_id": str(logo.id), "reason": "logo_informs_brand_profile_only"}
    ]
    assert provenance["brand_profile"]["has_official_logo"] is True
    assert provenance["purpose"] == "hero"
    assert provenance["brand_mode"] == brief.brand_strategy.value
    assert provenance["creative_level"] == brief.creative_level.value
    assert provenance["prompt_version"] == composed.version
    assert provenance["provider"] == "higgsfield" and provenance["job_id"] == "job-1"
    assert provenance["validation"]["status"] == "passed"
    assert provenance["cost_semantics"] == COST_SEMANTICS
    assert provenance["estimated_generation_units"] == 2.0
    for forbidden in ("://", "X-Amz", "Signature", "presign", "Authorization", "secret", "api_key"):
        assert forbidden.lower() not in serialized.lower()
    assert composed.positive_prompt not in serialized  # fingerprinted, never stored verbatim
