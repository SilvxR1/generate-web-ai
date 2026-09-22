"""Image QA (P2.7) — pure domain tests over synthetic in-memory images.

No network, storage, database or provider. The property under test throughout:
NOT CHECKED IS NEVER PASSED — not_performed / not_applicable are distinct
statuses and never fold into pass, and only BLOCKING checks can make a candidate
ineligible."""

import json
import random
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.domain.creative import brand_intelligence as bi
from app.domain.creative.image_qa import (
    CheckKind,
    CheckSeverity,
    CheckStatus,
    ImageQACheck,
    ImageQARequirements,
    ImageQAResult,
    direction_is_approval_eligible,
    requirements_from_provenance,
    run_image_qa,
    unavailable_result,
)
from app.domain.creative.image_qa import checks as checks_module
from app.domain.creative.image_qa import pixels as pixels_module
from app.domain.creative.image_qa.models import SEMANTIC_CHECKS

FIXTURES = Path(__file__).parent / "fixtures" / "image_qa"
BEIGE = (211, 205, 191)  # a warm studio backdrop: neutral by chroma
PINK, PEACH, MAUVE = (234, 125, 135), (237, 176, 141), (138, 105, 133)
HEX_PALETTE = ("#EDB08D", "#8A6985", "#EA7D87")
FIXED_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _canvas(size=(320, 180), color=BEIGE, mode="RGB") -> Image.Image:
    return Image.new(mode, size, color)


def _patches(patches: list[tuple[tuple[int, int, int, int], tuple]], size=(320, 180), bg=BEIGE, mode="RGB"):
    image = _canvas(size, bg, mode)
    draw = ImageDraw.Draw(image)
    for box, color in patches:
        draw.rectangle(box, fill=color)
    return image


def _noise(image: Image.Image, box: tuple[int, int, int, int], seed: int = 7) -> Image.Image:
    """Deterministic high-activity texture (a stand-in for a detailed subject)."""
    rng = random.Random(seed)
    left, top, right, bottom = box
    count = (right - left) * (bottom - top) * 3
    region = Image.frombytes("RGB", (right - left, bottom - top), bytes(rng.randrange(40, 200) for _ in range(count)))
    image.paste(region, (left, top))
    return image


def _requirements(**kwargs) -> ImageQARequirements:
    base = {"aspect_ratio": "16:9", "brand_palette": (), "subject_side": "right", "purpose": "hero"}
    base.update(kwargs)
    return ImageQARequirements(**base)


def _run(image: Image.Image | bytes, **kwargs) -> ImageQAResult:
    data = image if isinstance(image, bytes) else _png(image)
    return run_image_qa(data, _requirements(**kwargs), now=FIXED_NOW)


def _check(result: ImageQAResult, name: str) -> ImageQACheck:
    return next(check for check in result.checks if check.name == name)


# --- image integrity -------------------------------------------------------------------------


def test_a_valid_image_passes_integrity_with_its_facts():
    check = _check(_run(_canvas()), "image_integrity")

    assert check.status is CheckStatus.PASS and check.kind is CheckKind.DETERMINISTIC
    assert check.evidence["format"] == "PNG" and (check.evidence["width"], check.evidence["height"]) == (320, 180)
    assert check.evidence["byte_size"] > 0 and check.evidence["mode"] == "RGB"


def test_a_truncated_image_fails_integrity_and_is_blocking():
    result = _run(_png(_canvas())[:60])

    check = _check(result, "image_integrity")
    assert check.status is CheckStatus.FAIL and check.severity is CheckSeverity.BLOCKING
    assert result.approval_eligible is False and result.overall_status is CheckStatus.FAIL
    assert result.blocking_reasons and result.blocking_reasons[0].startswith("image_integrity")
    # Everything pixel-based is then NOT_PERFORMED — never a pass on an undecodable file.
    for name in ("aspect_ratio", "brand_palette_adherence", "hero_negative_space"):
        assert _check(result, name).status is CheckStatus.NOT_PERFORMED


@pytest.mark.parametrize("data", [b"", b"not an image at all", b"<html>error page</html>"])
def test_non_images_fail_integrity(data: bytes):
    assert _check(_run(data), "image_integrity").status is CheckStatus.FAIL


def test_a_valid_but_unexpected_format_fails_integrity():
    buffer = BytesIO()
    _canvas((16, 9)).save(buffer, "GIF")

    assert _check(_run(buffer.getvalue()), "image_integrity").status is CheckStatus.FAIL


def test_exceeding_our_own_analysis_limits_is_not_performed_never_a_defect(monkeypatch: pytest.MonkeyPatch):
    bomb = _png(Image.new("L", (5000, 5000)))  # 25 MP but a few KB
    monkeypatch.setattr(Image.Image, "load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not decode")))

    result = _run(bomb)

    check = _check(result, "image_integrity")
    assert check.status is CheckStatus.NOT_PERFORMED and check.reason == "analysis_limits_exceeded"
    assert result.approval_eligible is True  # our budget is not the image's fault
    assert _check(result, "aspect_ratio").status is CheckStatus.NOT_PERFORMED


def test_oversized_bytes_are_not_performed():
    result = _run(b"\xff\xd8\xff" + bytes(bi.MAX_IMAGE_BYTES))

    assert _check(result, "image_integrity").reason == "analysis_limits_exceeded"
    assert result.approval_eligible is True


def test_qa_reuses_the_p26_image_limits_rather_than_defining_its_own():
    assert pixels_module.MAX_IMAGE_BYTES == bi.MAX_IMAGE_BYTES
    assert pixels_module.MAX_IMAGE_SIDE == bi.MAX_IMAGE_SIDE and pixels_module.MAX_IMAGE_PIXELS == bi.MAX_IMAGE_PIXELS


# --- aspect ratio ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "status"),
    [
        ((1600, 900), CheckStatus.PASS),  # exact 16:9
        ((1696, 960), CheckStatus.PASS),  # what providers really emit (0.6% off): NOT exact, and must pass
        ((1600, 1000), CheckStatus.WARNING),  # 16:10 — 10% off, croppable
        ((1500, 1000), CheckStatus.FAIL),  # 3:2 — 15.6% off
        ((900, 1600), CheckStatus.FAIL),  # portrait
    ],
)
def test_aspect_ratio_uses_a_tolerance_not_float_equality(size, status):
    result = _run(Image.new("RGB", size, BEIGE))

    check = _check(result, "aspect_ratio")
    assert check.status is status
    assert result.approval_eligible is (status is not CheckStatus.FAIL)


def test_aspect_ratio_evidence_explains_the_measurement():
    evidence = _check(_run(Image.new("RGB", (1696, 960), BEIGE)), "aspect_ratio").evidence

    assert evidence["expected_ratio_text"] == "16:9"
    assert evidence["actual_width"] == 1696 and evidence["actual_height"] == 960
    assert evidence["expected_ratio"] == pytest.approx(1.7778, abs=1e-4)
    assert evidence["actual_ratio"] == pytest.approx(1.7667, abs=1e-4)
    assert evidence["deviation"] == pytest.approx(0.0062, abs=1e-4)
    assert evidence["tolerance"] == 0.02 and evidence["fail_deviation"] == 0.10


def test_the_pass_tolerance_matches_the_existing_metadata_validator():
    from app.domain.creative.asset_validation import _ASPECT_TOLERANCE

    assert checks_module.ASPECT_PASS_TOLERANCE == _ASPECT_TOLERANCE  # never two contradictory tolerances


def test_no_or_invalid_aspect_requirement_is_not_applicable_or_not_performed():
    assert _check(_run(_canvas(), aspect_ratio=None), "aspect_ratio").status is CheckStatus.NOT_APPLICABLE
    assert _check(_run(_canvas(), aspect_ratio="wide"), "aspect_ratio").status is CheckStatus.NOT_PERFORMED


# --- brand palette adherence -------------------------------------------------------------------


def _palette_check(image: Image.Image, palette=HEX_PALETTE) -> ImageQACheck:
    return _check(_run(image, brand_palette=palette), "brand_palette_adherence")


def test_an_empty_palette_is_not_applicable_never_pass():
    check = _check(_run(_canvas()), "brand_palette_adherence")

    assert check.status is CheckStatus.NOT_APPLICABLE and check.reason == "no_brand_palette_requested"


def test_an_image_strongly_matching_the_palette_passes_with_per_color_evidence():
    image = _patches([((20, 20, 80, 70), PINK), ((100, 20, 160, 70), PEACH), ((180, 20, 240, 70), MAUVE)])

    check = _palette_check(image)

    assert check.status is CheckStatus.PASS and check.kind is CheckKind.HEURISTIC
    assert check.severity is CheckSeverity.WARNING
    evidence = check.evidence
    assert [c["present"] for c in evidence["requested_palette"]] == [True, True, True]
    assert all(c["coverage"] >= 0.03 for c in evidence["requested_palette"])
    assert evidence["present_count"] == 3 and evidence["required_count"] == 2
    assert evidence["neutral_fraction"] > 0.7  # the beige backdrop is neutral, and that is fine
    assert evidence["analysis_pixel_count"] > 10_000


def test_an_image_weakly_matching_the_palette_warns_and_explains_why():
    green, olive, black = (110, 150, 120), (110, 100, 60), (26, 22, 19)
    image = _patches([((20, 20, 80, 70), green), ((100, 20, 160, 70), olive), ((180, 20, 240, 70), black)])

    check = _palette_check(image)

    assert check.status is CheckStatus.WARNING
    evidence = check.evidence
    assert evidence["present_count"] == 0 and all(not c["present"] for c in evidence["requested_palette"])
    assert evidence["brand_related_pixel_fraction"] == 0.0
    assert all(c["nearest_detected_delta_e"] is not None for c in evidence["requested_palette"])
    assert evidence["dominant_detected_colors"][0]["chromatic"] is False  # the backdrop dominates
    assert "not found" in check.summary


def test_a_neutral_heavy_image_with_small_brand_accents_passes():
    image = _patches([((20, 20, 45, 45), PINK), ((60, 20, 85, 45), PEACH)])  # ~1.1% each, rest is backdrop

    check = _palette_check(image)

    assert check.status is CheckStatus.PASS  # two of three present is enough for a palette accent
    assert check.evidence["neutral_fraction"] > 0.9


def test_a_single_accent_of_a_three_color_palette_is_only_a_warning():
    image = _patches([((20, 20, 60, 60), PINK)])

    check = _palette_check(image)

    assert check.status is CheckStatus.WARNING and check.evidence["present_count"] == 1
    assert check.severity is CheckSeverity.WARNING  # and can never block


def test_a_single_color_palette_needs_that_color():
    assert _palette_check(_patches([((20, 20, 60, 60), PINK)]), palette=("#EA7D87",)).status is CheckStatus.PASS
    assert _palette_check(_canvas(), palette=("#EA7D87",)).status is CheckStatus.WARNING


def test_shaded_and_lit_versions_of_a_brand_color_still_count():
    darker, lighter = (200, 95, 105), (245, 165, 172)
    image = _patches([((20, 20, 70, 70), darker), ((100, 20, 150, 70), lighter)])

    assert _palette_check(image, palette=("#EA7D87",)).evidence["requested_palette"][0]["present"] is True


def test_a_different_hue_of_similar_lightness_does_not_count():
    image = _patches([((20, 20, 120, 100), (110, 150, 120))])

    assert _palette_check(image, palette=("#EA7D87",)).status is CheckStatus.WARNING


def test_transparent_pixels_are_ignored_by_the_analysis():
    transparent = _patches(
        [((20, 20, 80, 70), (*PINK, 255)), ((100, 20, 160, 70), (*PEACH, 255)), ((180, 20, 240, 70), (*MAUVE, 255))],
        bg=(255, 255, 255, 0),
        mode="RGBA",
    )

    check = _palette_check(transparent)

    assert check.status is CheckStatus.PASS
    assert check.evidence["neutral_fraction"] < 0.05  # the transparent backdrop is not counted as neutral pixels
    assert check.evidence["analysis_pixel_count"] < 0.2 * 160 * 90


def test_a_fully_transparent_image_cannot_be_analyzed():
    check = _palette_check(Image.new("RGBA", (64, 36), (0, 0, 0, 0)))

    assert check.status is CheckStatus.NOT_PERFORMED and check.reason == "no_opaque_pixels"


def test_a_monochrome_image_is_all_neutral_and_warns_against_a_chromatic_palette():
    check = _palette_check(Image.new("L", (320, 180), 128).convert("RGB"))

    assert check.status is CheckStatus.WARNING
    assert check.evidence["neutral_fraction"] == 1.0 and check.evidence["chromatic_fraction"] == 0.0


def test_a_low_chroma_brand_color_is_compared_by_plain_color_distance():
    grey_image = Image.new("RGB", (320, 180), (128, 128, 128))

    assert _palette_check(grey_image, palette=("#808080",)).status is CheckStatus.PASS
    assert _palette_check(grey_image, palette=("#202020",)).status is CheckStatus.WARNING


def test_a_palette_in_an_unmeasurable_notation_is_not_performed_not_guessed():
    check = _palette_check(_canvas(), palette=("oklch(0.7 0.1 30)", "red"))

    assert check.status is CheckStatus.NOT_PERFORMED and check.reason == "palette_not_measurable"
    assert check.evidence["unmeasurable_values"] == ["oklch(0.7 0.1 30)", "red"]


def test_unmeasurable_entries_are_reported_but_do_not_hide_measurable_ones():
    image = _patches([((20, 20, 80, 70), PINK)])

    check = _palette_check(image, palette=("#EA7D87", "red"))

    assert check.status is CheckStatus.PASS and check.evidence["unmeasurable_values"] == ["red"]


def test_palette_analysis_is_deterministic():
    image = _noise(_patches([((20, 20, 80, 70), PINK)]), (150, 0, 320, 180))

    first, second = _run(image, brand_palette=HEX_PALETTE), _run(image, brand_palette=HEX_PALETTE)

    assert first.model_dump_json() == second.model_dump_json()


def test_the_thresholds_are_recorded_with_every_palette_measurement():
    thresholds = _palette_check(_canvas()).evidence["thresholds"]

    assert thresholds["min_presence_fraction"] == checks_module.MIN_PRESENCE_FRACTION == 0.005
    assert thresholds["neutral_chroma"] == checks_module.NEUTRAL_CHROMA


# --- composition / negative space --------------------------------------------------------------


def test_a_calm_left_and_a_busy_right_passes_as_a_heuristic():
    image = _noise(_canvas(), (190, 0, 320, 180))

    check = _check(_run(image), "hero_negative_space")

    assert check.status is CheckStatus.PASS and check.kind is CheckKind.HEURISTIC
    assert check.evidence["left_region_activity"] < 0.5
    assert check.evidence["right_region_activity"] > 3
    assert check.evidence["activity_ratio"] < checks_module.NEGATIVE_SPACE_MAX_RATIO
    assert check.evidence["expected_negative_space_side"] == "left"
    assert "does not detect a subject" in check.evidence["claim"]


def test_the_check_makes_no_subject_claim_in_its_wording():
    check = _check(_run(_noise(_canvas(), (190, 0, 320, 180))), "hero_negative_space")

    assert "subject detected" not in check.summary.lower() and "activity" in check.summary


def test_busy_everywhere_warns_and_never_blocks():
    result = _run(_noise(_canvas(), (0, 0, 320, 180)))

    check = _check(result, "hero_negative_space")
    assert check.status is CheckStatus.WARNING and check.severity is CheckSeverity.WARNING
    assert result.approval_eligible is True and result.overall_status is CheckStatus.WARNING


def test_a_subject_spilling_into_the_empty_side_warns():
    image = _noise(_canvas(), (70, 0, 320, 180))  # busy from 22% across: ~45% of the empty (left 40%) region

    check = _check(_run(image), "hero_negative_space")

    assert check.status is CheckStatus.WARNING
    assert check.evidence["negative_space_active_fraction"] > checks_module.NEGATIVE_SPACE_MAX_ACTIVE_FRACTION


def test_a_slight_intrusion_into_the_empty_side_is_tolerated():
    image = _noise(_canvas(), (120, 0, 320, 180))  # only ~6% of the empty region is busy

    check = _check(_run(image), "hero_negative_space")

    assert check.status is CheckStatus.PASS
    assert check.evidence["negative_space_active_fraction"] <= checks_module.NEGATIVE_SPACE_MAX_ACTIVE_FRACTION


def test_a_mirrored_composition_checks_the_right_side():
    image = _noise(_canvas(), (0, 0, 130, 180))

    check = _check(_run(image, subject_side="left"), "hero_negative_space")

    assert check.status is CheckStatus.PASS and check.evidence["expected_negative_space_side"] == "right"


def test_a_blank_image_has_no_clear_subject_side_so_it_warns():
    check = _check(_run(_canvas()), "hero_negative_space")

    assert check.status is CheckStatus.WARNING and check.reason == "no_detectable_activity_on_subject_side"


@pytest.mark.parametrize("side", ["center", "none", None])
def test_a_non_directional_scene_has_no_negative_space_requirement(side):
    check = _check(_run(_canvas(), subject_side=side), "hero_negative_space")

    assert check.status is CheckStatus.NOT_APPLICABLE  # not "pass"


# --- semantic checks: NOT_PERFORMED, never pass ----------------------------------------------


def test_every_semantic_check_is_not_performed_by_default():
    result = _run(_canvas())

    assert set(SEMANTIC_CHECKS) == {
        "unwanted_text",
        "interface_detection",
        "unwanted_logo",
        "logo_distortion",
        "subject_consistency",
        "brand_drift",
        "visual_artifacts",
    }
    for name in SEMANTIC_CHECKS:
        check = _check(result, name)
        assert check.status is CheckStatus.NOT_PERFORMED and check.kind is CheckKind.SEMANTIC
        assert check.reason == "no_semantic_analyzer_configured" and check.severity is CheckSeverity.INFORMATIONAL
        assert "not a pass" in check.summary
    assert set(SEMANTIC_CHECKS) <= set(result.coverage.not_performed)


def test_palette_adherence_and_semantic_brand_drift_are_distinct_checks():
    result = _run(_canvas(), brand_palette=HEX_PALETTE)

    assert _check(result, "brand_palette_adherence").status is CheckStatus.WARNING
    # measuring pixels is not judging the brand
    assert _check(result, "brand_drift").status is CheckStatus.NOT_PERFORMED


def test_a_pass_never_hides_the_coverage_gaps():
    image = _noise(_patches([((20, 20, 80, 70), PINK), ((100, 20, 160, 70), PEACH)]), (190, 0, 320, 180))

    result = _run(image, brand_palette=HEX_PALETTE)

    assert result.overall_status is CheckStatus.PASS
    assert set(result.coverage.performed) == {
        "image_integrity",
        "aspect_ratio",
        "brand_palette_adherence",
        "hero_negative_space",
    }
    assert len(result.coverage.not_performed) == 7  # visible, not silently passed


class _AlwaysPass:
    check_name = "unwanted_text"

    def analyze(self, image, requirements) -> ImageQACheck:
        return ImageQACheck(
            name="ignored",
            status=CheckStatus.PASS,
            kind=CheckKind.DETERMINISTIC,
            severity=CheckSeverity.WARNING,
            method="fake_ocr",
            summary="No text found.",
        )


class _Exploding:
    check_name = "interface_detection"

    def analyze(self, image, requirements) -> ImageQACheck:
        raise RuntimeError("model crashed")


def test_a_registered_analyzer_replaces_the_placeholder_and_is_labelled_semantic():
    result = run_image_qa(_png(_canvas()), _requirements(), analyzers={"unwanted_text": _AlwaysPass()}, now=FIXED_NOW)

    check = _check(result, "unwanted_text")
    assert check.status is CheckStatus.PASS and check.kind is CheckKind.SEMANTIC and check.name == "unwanted_text"
    assert "unwanted_text" in result.coverage.performed and "interface_detection" in result.coverage.not_performed


def test_a_failing_analyzer_degrades_to_not_performed_never_to_pass():
    result = run_image_qa(
        _png(_canvas()), _requirements(), analyzers={"interface_detection": _Exploding()}, now=FIXED_NOW
    )

    check = _check(result, "interface_detection")
    assert check.status is CheckStatus.NOT_PERFORMED and check.reason == "analyzer_error"


def test_analyzers_are_not_run_on_an_undecodable_image():
    result = run_image_qa(b"garbage", _requirements(), analyzers={"unwanted_text": _AlwaysPass()}, now=FIXED_NOW)

    assert _check(result, "unwanted_text").reason == "image_not_decodable"


# --- policy: blocking vs warning, overall status ---------------------------------------------------


def test_only_blocking_checks_make_a_candidate_ineligible():
    severe_aspect = _run(Image.new("RGB", (1500, 1000), BEIGE))
    palette_warning = _run(_canvas(), brand_palette=HEX_PALETTE)
    composition_warning = _run(_noise(_canvas(), (0, 0, 320, 180)))

    assert severe_aspect.approval_eligible is False and "aspect_ratio" in severe_aspect.blocking_reasons[0]
    for result in (palette_warning, composition_warning):
        assert result.approval_eligible is True and result.blocking_reasons == [] and result.warnings


def test_overall_status_summarizes_only_the_checks_that_ran():
    assert _run(_noise(_canvas(), (190, 0, 320, 180))).overall_status is CheckStatus.PASS
    assert _run(_canvas(), brand_palette=HEX_PALETTE).overall_status is CheckStatus.WARNING
    assert _run(b"junk").overall_status is CheckStatus.FAIL


def test_when_nothing_could_run_the_overall_status_is_not_performed():
    result = unavailable_result(_requirements(), reason="artifact_unavailable", detail="timeout", now=FIXED_NOW)

    assert result.overall_status is CheckStatus.NOT_PERFORMED and result.approval_eligible is True
    assert result.coverage.performed == [] and len(result.coverage.not_performed) == 11
    assert all(check.status is CheckStatus.NOT_PERFORMED for check in result.checks)
    assert _check(result, "image_integrity").evidence == {"fetch_error": "timeout"}


def test_an_unavailable_artifact_is_never_a_block_and_never_a_pass():
    result = unavailable_result(_requirements(), reason="artifact_unavailable", now=FIXED_NOW)

    assert result.approval_eligible is True
    assert CheckStatus.PASS not in {check.status for check in result.checks}


# --- requirements, provenance, eligibility ---------------------------------------------------------


def test_requirements_are_read_from_recorded_provenance():
    spec = {
        "purpose": "hero",
        "scene_plan": {"aspect_ratio": "16:9", "subject_side": "right", "brand_palette": ["#EDB08D", "#8A6985"]},
    }

    req = requirements_from_provenance(spec)

    assert (req.aspect_ratio, req.subject_side, req.purpose) == ("16:9", "right", "hero")
    assert req.brand_palette == ("#EDB08D", "#8A6985")


@pytest.mark.parametrize(
    "spec", [{}, {"scene_plan": None}, {"scene_plan": {"brand_palette": "nope", "aspect_ratio": 3}}]
)
def test_missing_or_malformed_provenance_yields_empty_requirements(spec):
    assert requirements_from_provenance(spec) == ImageQARequirements()


def test_the_result_serializes_to_concise_json_and_round_trips():
    image = _noise(_patches([((20, 20, 80, 70), PINK)]), (190, 0, 320, 180))
    result = _run(image, brand_palette=HEX_PALETTE)

    dumped = result.model_dump(mode="json")
    text = json.dumps(dumped)

    assert ImageQAResult.model_validate(json.loads(text)) == result
    assert dumped["version"] == "p2.7-v1" and dumped["performed_at"].startswith("2026-01-01")
    assert dumped["requirements"] == {
        "aspect_ratio": "16:9",
        "brand_palette": list(HEX_PALETTE),
        "subject_side": "right",
        "purpose": "hero",
    }
    assert len(text) < 12_000  # concise measurements, not pixel dumps
    for forbidden in ("http", "base64", "presign", "X-Amz"):
        assert forbidden not in text


@pytest.mark.parametrize(
    ("metadata", "eligible"),
    [
        (None, True),
        ({}, True),  # older rows carry no QA
        ({"creative_spec": {}}, True),
        ({"creative_spec": {"visual_qa": {"approval_eligible": True}}}, True),
        ({"creative_spec": {"visual_qa": {"overall_status": "not_performed", "approval_eligible": True}}}, True),
        ({"creative_spec": {"visual_qa": {"approval_eligible": False}}}, False),
    ],
)
def test_only_a_recorded_blocking_failure_makes_a_direction_ineligible(metadata, eligible):
    assert direction_is_approval_eligible(metadata) is eligible


# --- real fixtures (downscaled copies of Experiments 5 and 6; thresholds were NOT tuned to them) ----------


def test_experiment_5_fixture_measurements():
    data = (FIXTURES / "exp5_p25_hero_480.jpg").read_bytes()

    result = run_image_qa(data, _requirements(brand_palette=()), now=FIXED_NOW)

    assert _check(result, "image_integrity").status is CheckStatus.PASS
    assert _check(result, "aspect_ratio").status is CheckStatus.PASS  # 480x272 is 16:9 within tolerance
    assert _check(result, "brand_palette_adherence").status is CheckStatus.NOT_APPLICABLE  # P2.5 had no palette
    negative = _check(result, "hero_negative_space")
    assert negative.status is CheckStatus.PASS and negative.evidence["left_region_activity"] < 0.5
    assert result.approval_eligible is True


def test_experiment_6_fixture_measurements_show_weak_palette_adherence():
    data = (FIXTURES / "exp6_p26_hero_480.jpg").read_bytes()

    result = run_image_qa(data, _requirements(brand_palette=HEX_PALETTE), now=FIXED_NOW)

    palette = _check(result, "brand_palette_adherence")
    assert palette.status is CheckStatus.WARNING  # measured by the real algorithm, not hard-coded
    evidence = palette.evidence
    assert evidence["present_count"] == 0
    assert all(color["coverage"] < 0.005 for color in evidence["requested_palette"])  # none reaches presence
    assert evidence["neutral_fraction"] > 0.85  # a warm neutral backdrop dominates
    assert _check(result, "hero_negative_space").status is CheckStatus.PASS
    assert result.approval_eligible is True and result.overall_status is CheckStatus.WARNING  # warns, never blocks
