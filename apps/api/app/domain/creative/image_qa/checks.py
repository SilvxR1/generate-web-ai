"""The implemented Image QA checks (P2.7): two DETERMINISTIC, two HEURISTIC.

Every threshold below is a named, versioned constant with the reason it has that
value, so it is easy to audit and tune once production outputs have been seen.
Nothing here claims to understand what the image DEPICTS: these are properties
of pixels. What needs understanding (text, UI, logos, artifacts, brand drift)
lives behind the SemanticAnalyzer seam in runner.py and is NOT_PERFORMED today.

Thresholds and why
------------------
ASPECT_PASS_TOLERANCE 0.02      identical to the metadata validator's existing
                                tolerance; providers emit 1696x960 for "16:9"
                                (deviation 0.6%), so exact equality is wrong.
ASPECT_FAIL_DEVIATION 0.10      16:10 is exactly 10% off 16:9 — still croppable;
                                beyond that (e.g. 3:2 = 15.6%) a hero crop loses
                                real content. FAIL only beyond this: BLOCKING.
NEUTRAL_CHROMA 12.0             CIELAB chroma (C*) below which a color has no
                                usable hue (greys, warm/cool whites, beige
                                backdrops sit around C* 3-10).
MATCH_CHROMATICITY_DISTANCE 12  distance in the (a*, b*) plane inside which a
                                pixel counts as the "same hue and saturation"
                                as a brand color (≈ +/-17 deg at C* 40).
MATCH_LIGHTNESS_DISTANCE 25     lightness allowance so shaded and lit versions
                                of a brand color still count (studio light
                                changes L* a lot; hue barely).
MATCH_NEUTRAL_DELTA_E 15        a low-chroma brand color (a grey) has no hue to
                                compare, so plain CIE76 distance is used.
MIN_PRESENCE_FRACTION 0.005     0.5% of the image ≈ a 90x90 px patch at 1696x960:
                                the smallest area read as a deliberate accent
                                rather than incidental noise.
MIN_PRESENT_SHARE 0.5           at least half of the requested colors must be
                                present: a brand palette is a SET, so one color
                                alone is weak evidence of adherence.
NEGATIVE_SPACE_MAX_RATIO 0.35   the empty side has at most ~1/3 of the subject
                                side's activity (a studio backdrop is ≈0.02-0.1).
NEGATIVE_SPACE_MAX_ACTIVE_FRACTION 0.15
                                at most 15% of the empty side's cells may be
                                "busy", which catches objects spilling into it.

Palette adherence never FAILS in P2.7: it is a warning-only measurement until
real production outputs show where a blocking threshold belongs.
"""

import math
from typing import Any

from PIL import Image

from app.domain.creative.image_qa.models import (
    CHECK_ASPECT_RATIO,
    CHECK_BRAND_PALETTE,
    CHECK_IMAGE_INTEGRITY,
    CHECK_NEGATIVE_SPACE,
    CheckKind,
    CheckSeverity,
    CheckStatus,
    ImageQACheck,
    ImageQARequirements,
)
from app.domain.creative.image_qa.pixels import (
    ALPHA_CUTOFF,
    DecodedImage,
    ImageDecodeError,
    Lab,
    delta_e,
    hex_to_rgb,
    rgb_to_hex,
    rgb_to_lab,
)

ASPECT_PASS_TOLERANCE = 0.02
ASPECT_FAIL_DEVIATION = 0.10

NEUTRAL_CHROMA = 12.0
NEUTRAL_MIN_LIGHTNESS = 12.0
MATCH_CHROMATICITY_DISTANCE = 12.0
MATCH_LIGHTNESS_DISTANCE = 25.0
MATCH_NEUTRAL_DELTA_E = 15.0
MIN_PRESENCE_FRACTION = 0.005
MIN_PRESENT_SHARE = 0.5
DOMINANT_MERGE_DELTA_E = 15.0
MAX_DOMINANT = 6
QUANT_SHIFT = 4

REGION_FRACTION = 0.4
NEGATIVE_SPACE_MAX_RATIO = 0.35
NEGATIVE_SPACE_MAX_ACTIVE_FRACTION = 0.15
ACTIVE_CELL_THRESHOLD = 4.0
MIN_SUBJECT_ACTIVITY = 1.0

METHOD_INTEGRITY = "pillow_bounded_decode"
METHOD_ASPECT = "decoded_dimensions_vs_contract_ratio"
METHOD_PALETTE = "cielab_chromaticity_proximity"
METHOD_NEGATIVE_SPACE = "region_luminance_gradient_activity"


def not_performed(
    name: str,
    kind: CheckKind,
    severity: CheckSeverity,
    method: str,
    reason: str,
    summary: str,
    evidence: dict | None = None,
) -> ImageQACheck:
    return ImageQACheck(
        name=name,
        status=CheckStatus.NOT_PERFORMED,
        kind=kind,
        severity=severity,
        method=method,
        summary=summary,
        reason=reason,
        evidence=evidence or {},
    )


def _not_applicable(
    name: str, kind: CheckKind, severity: CheckSeverity, method: str, reason: str, summary: str
) -> ImageQACheck:
    return ImageQACheck(
        name=name,
        status=CheckStatus.NOT_APPLICABLE,
        kind=kind,
        severity=severity,
        method=method,
        summary=summary,
        reason=reason,
    )


# --- A. image integrity (DETERMINISTIC, BLOCKING) --------------------------------------------


def image_integrity_check(decoded: DecodedImage | None, error: ImageDecodeError | None) -> ImageQACheck:
    common: dict[str, Any] = {
        "name": CHECK_IMAGE_INTEGRITY,
        "kind": CheckKind.DETERMINISTIC,
        "severity": CheckSeverity.BLOCKING,
    }
    if decoded is not None:
        return ImageQACheck(
            status=CheckStatus.PASS,
            method=METHOD_INTEGRITY,
            summary="The image decodes cleanly.",
            evidence={
                "format": decoded.format,
                "width": decoded.width,
                "height": decoded.height,
                "mode": decoded.mode,
                "byte_size": decoded.byte_size,
            },
            **common,
        )
    assert error is not None
    if error.is_defect:
        return ImageQACheck(
            status=CheckStatus.FAIL,
            method=METHOD_INTEGRITY,
            reason=error.code,
            summary="The generated file is not a valid image of an expected format.",
            evidence={"decode_error": error.code},
            **common,
        )
    return ImageQACheck(
        status=CheckStatus.NOT_PERFORMED,
        method=METHOD_INTEGRITY,
        reason="analysis_limits_exceeded",
        summary="The image is larger than the analysis limits, so it was not inspected.",
        evidence={"decode_error": error.code},
        **common,
    )


# --- B. aspect ratio (DETERMINISTIC, BLOCKING when severe) -----------------------------------


def _parse_ratio(text: str) -> float | None:
    try:
        left, right = text.split(":")
        value = int(left) / int(right)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def aspect_ratio_check(decoded: DecodedImage, requirements: ImageQARequirements) -> ImageQACheck:
    common: dict[str, Any] = {
        "name": CHECK_ASPECT_RATIO,
        "kind": CheckKind.DETERMINISTIC,
        "severity": CheckSeverity.BLOCKING,
        "method": METHOD_ASPECT,
    }
    if not requirements.aspect_ratio:
        return _not_applicable(
            summary="The contract sets no aspect ratio.", reason="no_aspect_ratio_requirement", **common
        )
    expected = _parse_ratio(requirements.aspect_ratio)
    if expected is None:
        return not_performed(
            reason="invalid_expected_ratio", summary="The contract's aspect ratio could not be parsed.", **common
        )
    actual = decoded.width / decoded.height
    deviation = abs(actual - expected) / expected
    evidence = {
        "expected_ratio_text": requirements.aspect_ratio,
        "expected_ratio": round(expected, 4),
        "actual_width": decoded.width,
        "actual_height": decoded.height,
        "actual_ratio": round(actual, 4),
        "deviation": round(deviation, 4),
        "tolerance": ASPECT_PASS_TOLERANCE,
        "fail_deviation": ASPECT_FAIL_DEVIATION,
    }
    size = f"{decoded.width}x{decoded.height}"
    if deviation <= ASPECT_PASS_TOLERANCE:
        status = CheckStatus.PASS
        summary = f"{size} matches {requirements.aspect_ratio} within {ASPECT_PASS_TOLERANCE:.0%}."
    elif deviation <= ASPECT_FAIL_DEVIATION:
        status = CheckStatus.WARNING
        summary = f"{size} is {deviation:.1%} off {requirements.aspect_ratio}; cropping will be needed."
    else:
        status = CheckStatus.FAIL
        summary = f"{size} is {deviation:.1%} off {requirements.aspect_ratio}: too different to use."
    return ImageQACheck(status=status, summary=summary, evidence=evidence, **common)


# --- C. brand palette adherence (HEURISTIC, WARNING only) ------------------------------------


def _opaque_pixels(thumbnail: Image.Image) -> list[tuple[int, int, int]]:
    raw = thumbnail.tobytes()
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 4) if raw[i + 3] >= ALPHA_CUTOFF]


def _is_neutral(lab: Lab) -> bool:
    return math.hypot(lab[1], lab[2]) < NEUTRAL_CHROMA or lab[0] < NEUTRAL_MIN_LIGHTNESS


class _Cluster:
    __slots__ = ("count", "seed", "sums")

    def __init__(self, seed: Lab, count: int, rgb: tuple[int, int, int]) -> None:
        self.seed, self.count = seed, count
        self.sums = [rgb[0] * count, rgb[1] * count, rgb[2] * count]

    def add(self, count: int, rgb: tuple[int, int, int]) -> None:
        self.count += count
        for index in range(3):
            self.sums[index] += rgb[index] * count

    def mean(self) -> tuple[int, int, int]:
        return (round(self.sums[0] / self.count), round(self.sums[1] / self.count), round(self.sums[2] / self.count))


def _dominant_clusters(pixels: list[tuple[int, int, int]]) -> list[_Cluster]:
    bins: dict[int, list[int]] = {}
    for red, green, blue in pixels:
        key = ((red >> QUANT_SHIFT) << 8) | ((green >> QUANT_SHIFT) << 4) | (blue >> QUANT_SHIFT)
        entry = bins.get(key)
        if entry is None:
            bins[key] = [1, red, green, blue]
        else:
            entry[0] += 1
            entry[1] += red
            entry[2] += green
            entry[3] += blue
    clusters: list[_Cluster] = []
    for _, (count, r_sum, g_sum, b_sum) in sorted(bins.items(), key=lambda item: (-item[1][0], item[0])):
        rgb = (round(r_sum / count), round(g_sum / count), round(b_sum / count))
        lab = rgb_to_lab(*rgb)
        for cluster in clusters:
            if delta_e(lab, cluster.seed) <= DOMINANT_MERGE_DELTA_E:
                cluster.add(count, rgb)
                break
        else:
            clusters.append(_Cluster(lab, count, rgb))
    return sorted(clusters, key=lambda c: (-c.count, rgb_to_hex(*c.mean())))


def brand_palette_check(decoded: DecodedImage, requirements: ImageQARequirements) -> ImageQACheck:
    common: dict[str, Any] = {
        "name": CHECK_BRAND_PALETTE,
        "kind": CheckKind.HEURISTIC,
        "severity": CheckSeverity.WARNING,
        "method": METHOD_PALETTE,
    }
    if not requirements.brand_palette:
        return _not_applicable(
            summary="No brand palette was requested for this image.", reason="no_brand_palette_requested", **common
        )

    requested: list[tuple[str, Lab, bool]] = []  # (hex, lab, low_chroma)
    unmeasurable: list[str] = []
    for value in requirements.brand_palette:
        rgb = hex_to_rgb(value)
        if rgb is None:
            unmeasurable.append(value)
            continue
        lab = rgb_to_lab(*rgb)
        requested.append((rgb_to_hex(*rgb), lab, math.hypot(lab[1], lab[2]) < NEUTRAL_CHROMA))
    if not requested:
        return not_performed(
            reason="palette_not_measurable",
            summary="The requested palette is not in a measurable #RRGGBB notation.",
            evidence={"unmeasurable_values": unmeasurable},
            **common,
        )

    pixels = _opaque_pixels(decoded.thumbnail)
    if not pixels:
        return not_performed(
            reason="no_opaque_pixels", summary="The image has no opaque pixels to analyze.", **common
        )

    total = len(pixels)
    cache: dict[tuple[int, int, int], Lab] = {}
    coverage = [0] * len(requested)
    related = neutral = 0
    for pixel in pixels:
        cached = cache.get(pixel)
        if cached is None:
            cached = cache[pixel] = rgb_to_lab(*pixel)
        lab = cached
        is_neutral = _is_neutral(lab)
        neutral += is_neutral
        hit_any = False
        for index, (_, brand_lab, low_chroma) in enumerate(requested):
            if low_chroma:
                hit = delta_e(lab, brand_lab) <= MATCH_NEUTRAL_DELTA_E
            else:
                hit = (
                    not is_neutral
                    and math.hypot(lab[1] - brand_lab[1], lab[2] - brand_lab[2]) <= MATCH_CHROMATICITY_DISTANCE
                    and abs(lab[0] - brand_lab[0]) <= MATCH_LIGHTNESS_DISTANCE
                )
            if hit:
                coverage[index] += 1
                hit_any = True
        related += hit_any

    clusters = _dominant_clusters(pixels)
    detected = [(rgb_to_hex(*c.mean()), rgb_to_lab(*c.mean()), c.count / total) for c in clusters]
    meaningful = [entry for entry in detected if entry[2] >= MIN_PRESENCE_FRACTION]

    requested_evidence: list[dict[str, Any]] = []
    present_count = 0
    for index, (hex_value, brand_lab, _) in enumerate(requested):
        fraction = coverage[index] / total
        present = fraction >= MIN_PRESENCE_FRACTION
        present_count += present
        nearest = min(meaningful, key=lambda e: delta_e(e[1], brand_lab)) if meaningful else None
        requested_evidence.append(
            {
                "hex": hex_value,
                "coverage": round(fraction, 4),
                "present": present,
                "nearest_detected_hex": nearest[0] if nearest else None,
                "nearest_detected_delta_e": round(delta_e(nearest[1], brand_lab), 1) if nearest else None,
            }
        )
    required = math.ceil(len(requested) * MIN_PRESENT_SHARE)

    dominant_evidence: list[dict[str, Any]] = []
    for hex_value, lab, share in detected[:MAX_DOMINANT]:
        nearest_brand = min(requested, key=lambda r: delta_e(lab, r[1]))
        dominant_evidence.append(
            {
                "hex": hex_value,
                "share": round(share, 4),
                "chromatic": not _is_neutral(lab),
                "nearest_brand_hex": nearest_brand[0],
                "nearest_brand_delta_e": round(delta_e(lab, nearest_brand[1]), 1),
            }
        )

    absent = [entry["hex"] for entry in requested_evidence if not entry["present"]]
    if present_count >= required:
        status = CheckStatus.PASS
        summary = f"{present_count} of {len(requested)} requested brand colors have meaningful presence in the image."
    else:
        status = CheckStatus.WARNING
        summary = (
            f"Only {present_count} of {len(requested)} requested brand colors have meaningful presence "
            f"(at least {required} expected); not found: {', '.join(absent)}."
        )
    evidence = {
        "requested_palette": requested_evidence,
        "dominant_detected_colors": dominant_evidence,
        "brand_related_pixel_fraction": round(related / total, 4),
        "neutral_fraction": round(neutral / total, 4),
        "chromatic_fraction": round(1 - neutral / total, 4),
        "present_count": present_count,
        "required_count": required,
        "analysis_pixel_count": total,
        "thresholds": {
            "neutral_chroma": NEUTRAL_CHROMA,
            "match_chromaticity_distance": MATCH_CHROMATICITY_DISTANCE,
            "match_lightness_distance": MATCH_LIGHTNESS_DISTANCE,
            "match_neutral_delta_e": MATCH_NEUTRAL_DELTA_E,
            "min_presence_fraction": MIN_PRESENCE_FRACTION,
            "min_present_share": MIN_PRESENT_SHARE,
        },
        "color_space": "CIELAB D65, CIE76 distance",
    }
    if unmeasurable:
        evidence["unmeasurable_values"] = unmeasurable
    return ImageQACheck(
        status=status, score=round(present_count / len(requested), 3), summary=summary, evidence=evidence, **common
    )


# --- D. negative space (HEURISTIC, WARNING only) ---------------------------------------------


def negative_space_check(decoded: DecodedImage, requirements: ImageQARequirements) -> ImageQACheck:
    common: dict[str, Any] = {
        "name": CHECK_NEGATIVE_SPACE,
        "kind": CheckKind.HEURISTIC,
        "severity": CheckSeverity.WARNING,
        "method": METHOD_NEGATIVE_SPACE,
    }
    side = requirements.subject_side
    if side not in ("left", "right"):
        return _not_applicable(
            summary="The scene has no left/right composition requirement.",
            reason="no_directional_composition_requirement",
            **common,
        )
    background = Image.new("RGBA", decoded.thumbnail.size, (255, 255, 255, 255))
    gray = Image.alpha_composite(background, decoded.thumbnail).convert("L")
    width, height = gray.size
    if width < 10 or height < 4:
        return not_performed(
            reason="image_too_small_for_regions", summary="The image is too small to compare regions.", **common
        )
    data = gray.tobytes()
    split = round(width * REGION_FRACTION)
    empty_columns = range(0, split) if side == "right" else range(width - split, width - 1)
    subject_columns = range(width - split, width - 1) if side == "right" else range(0, split)

    def region(columns: range) -> tuple[float, float]:
        cells = active = 0
        total = 0.0
        for y in range(height - 1):
            row = y * width
            for x in columns:
                value = (abs(data[row + x + 1] - data[row + x]) + abs(data[row + width + x] - data[row + x])) / 2
                total += value
                cells += 1
                active += value > ACTIVE_CELL_THRESHOLD
        return (total / cells, active / cells) if cells else (0.0, 0.0)

    empty_activity, empty_active = region(empty_columns)
    subject_activity, _ = region(subject_columns)
    if side == "right":
        left_activity, right_activity = empty_activity, subject_activity
    else:
        left_activity, right_activity = subject_activity, empty_activity
    ratio = empty_activity / subject_activity if subject_activity > 0 else None
    empty_name = "left" if side == "right" else "right"
    evidence = {
        "expected_negative_space_side": empty_name,
        "left_region_activity": round(left_activity, 3),
        "right_region_activity": round(right_activity, 3),
        "activity_ratio": round(ratio, 3) if ratio is not None else None,
        "negative_space_active_fraction": round(empty_active, 4),
        "region_fraction": REGION_FRACTION,
        "activity_unit": "mean absolute luminance step per pixel (0-255), <=160px thumbnail",
        "thresholds": {
            "max_ratio": NEGATIVE_SPACE_MAX_RATIO,
            "max_active_fraction": NEGATIVE_SPACE_MAX_ACTIVE_FRACTION,
            "active_cell_threshold": ACTIVE_CELL_THRESHOLD,
            "min_subject_activity": MIN_SUBJECT_ACTIVITY,
        },
        "claim": "relative visual activity of image regions only; it does not detect a subject",
    }
    if ratio is None or subject_activity < MIN_SUBJECT_ACTIVITY:
        return ImageQACheck(
            status=CheckStatus.WARNING,
            summary=f"The {side} side shows almost no visual activity, so no clear subject side was found.",
            reason="no_detectable_activity_on_subject_side",
            evidence=evidence,
            **common,
        )
    if ratio <= NEGATIVE_SPACE_MAX_RATIO and empty_active <= NEGATIVE_SPACE_MAX_ACTIVE_FRACTION:
        status = CheckStatus.PASS
        summary = f"The {empty_name} side is markedly calmer than the {side} side ({ratio:.2f}x the activity)."
    else:
        status = CheckStatus.WARNING
        summary = (
            f"The {empty_name} side is not markedly calmer than the {side} side "
            f"({ratio:.2f}x the activity, {empty_active:.0%} busy cells)."
        )
    return ImageQACheck(status=status, score=round(ratio, 3), summary=summary, evidence=evidence, **common)
