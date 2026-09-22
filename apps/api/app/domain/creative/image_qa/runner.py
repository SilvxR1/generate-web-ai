"""Image QA runner (P2.7): decode once, run every check, summarize honestly.

Provider-independent and pure: bytes + requirements in, `ImageQAResult` out.
No network, storage, database or provider — the caller (app.services.
generated_image_qa) is responsible for obtaining the bytes.

SEMANTIC ANALYZER SEAM. Text, UI, logo and artifact detection and semantic brand
drift require understanding image content. None is implemented in P2.7 (no OCR,
no vision model, no external service), so each is reported NOT_PERFORMED — a
visible coverage gap, never a pass. A future analyzer registers under its check
name and its result replaces the placeholder:

    run_image_qa(data, requirements, analyzers={"unwanted_text": MyOcrAnalyzer()})

An analyzer that raises degrades to NOT_PERFORMED (`analyzer_error`); it can
never turn an unchecked image into a passing one by failing.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from app.domain.creative.image_qa.checks import (
    METHOD_ASPECT,
    METHOD_INTEGRITY,
    METHOD_NEGATIVE_SPACE,
    METHOD_PALETTE,
    aspect_ratio_check,
    brand_palette_check,
    image_integrity_check,
    negative_space_check,
    not_performed,
)
from app.domain.creative.image_qa.models import (
    CHECK_ASPECT_RATIO,
    CHECK_BRAND_PALETTE,
    CHECK_IMAGE_INTEGRITY,
    CHECK_NEGATIVE_SPACE,
    SEMANTIC_CHECKS,
    CheckKind,
    CheckSeverity,
    CheckStatus,
    Coverage,
    ImageQACheck,
    ImageQARequirements,
    ImageQAResult,
)
from app.domain.creative.image_qa.pixels import DecodedImage, ImageDecodeError, decode_for_qa

SEMANTIC_METHOD = "semantic_analyzer_seam"

# (name, kind, severity, method) of every implemented check, in display order.
_IMPLEMENTED: tuple[tuple[str, CheckKind, CheckSeverity, str], ...] = (
    (CHECK_IMAGE_INTEGRITY, CheckKind.DETERMINISTIC, CheckSeverity.BLOCKING, METHOD_INTEGRITY),
    (CHECK_ASPECT_RATIO, CheckKind.DETERMINISTIC, CheckSeverity.BLOCKING, METHOD_ASPECT),
    (CHECK_BRAND_PALETTE, CheckKind.HEURISTIC, CheckSeverity.WARNING, METHOD_PALETTE),
    (CHECK_NEGATIVE_SPACE, CheckKind.HEURISTIC, CheckSeverity.WARNING, METHOD_NEGATIVE_SPACE),
)


class SemanticAnalyzer(Protocol):
    """One semantic check. Implementations must return a check named
    `check_name`; their kind is forced to SEMANTIC by the runner."""

    check_name: str

    def analyze(self, image: DecodedImage, requirements: ImageQARequirements) -> ImageQACheck: ...


def requirements_from_provenance(creative_spec: dict) -> ImageQARequirements:
    """The contract slice a generated image is checked against, read from the
    provenance the generation already recorded (scene_plan + purpose) — so QA
    needs no access to the live contract and reports exactly what was requested."""
    scene = creative_spec.get("scene_plan")
    scene = scene if isinstance(scene, dict) else {}
    palette = scene.get("brand_palette")
    ratio, side = scene.get("aspect_ratio"), scene.get("subject_side")
    purpose = creative_spec.get("purpose")
    return ImageQARequirements(
        aspect_ratio=ratio if isinstance(ratio, str) else None,
        brand_palette=tuple(str(value) for value in palette) if isinstance(palette, list) else (),
        subject_side=side if isinstance(side, str) else None,
        purpose=purpose if isinstance(purpose, str) else None,
    )


def _semantic_placeholder(name: str) -> ImageQACheck:
    return not_performed(
        name,
        CheckKind.SEMANTIC,
        CheckSeverity.INFORMATIONAL,
        SEMANTIC_METHOD,
        "no_semantic_analyzer_configured",
        "Not checked: no semantic analyzer is configured, so this is a coverage gap, not a pass.",
    )


def _run_semantic(
    name: str,
    decoded: DecodedImage | None,
    requirements: ImageQARequirements,
    analyzers: Mapping[str, SemanticAnalyzer],
) -> ImageQACheck:
    analyzer = analyzers.get(name)
    if analyzer is None:
        return _semantic_placeholder(name)
    if decoded is None:
        return not_performed(
            name,
            CheckKind.SEMANTIC,
            CheckSeverity.INFORMATIONAL,
            SEMANTIC_METHOD,
            "image_not_decodable",
            "Not checked: the image could not be decoded.",
        )
    try:
        result = analyzer.analyze(decoded, requirements)
    except Exception:  # noqa: BLE001 — an analyzer failure must never look like a pass
        return not_performed(
            name,
            CheckKind.SEMANTIC,
            CheckSeverity.INFORMATIONAL,
            SEMANTIC_METHOD,
            "analyzer_error",
            "Not checked: the semantic analyzer failed.",
        )
    return result.model_copy(update={"name": name, "kind": CheckKind.SEMANTIC})


def summarize(
    checks: list[ImageQACheck], requirements: ImageQARequirements, *, now: datetime | None = None
) -> ImageQAResult:
    blocking = [c for c in checks if c.status is CheckStatus.FAIL and c.severity is CheckSeverity.BLOCKING]
    warnings = [
        f"{c.name}: {c.summary}"
        for c in checks
        if c.status is CheckStatus.WARNING
        or (c.status is CheckStatus.FAIL and c.severity is not CheckSeverity.BLOCKING)
    ]
    statuses = {c.status for c in checks}
    if CheckStatus.FAIL in statuses:
        overall = CheckStatus.FAIL
    elif CheckStatus.WARNING in statuses:
        overall = CheckStatus.WARNING
    elif CheckStatus.PASS in statuses:
        overall = CheckStatus.PASS
    else:
        overall = CheckStatus.NOT_PERFORMED
    ran = (CheckStatus.PASS, CheckStatus.WARNING, CheckStatus.FAIL)
    return ImageQAResult(
        performed_at=now or datetime.now(UTC),
        overall_status=overall,
        approval_eligible=not blocking,
        blocking_reasons=[f"{c.name}: {c.summary}" for c in blocking],
        warnings=warnings,
        coverage=Coverage(
            performed=[c.name for c in checks if c.status in ran],
            not_performed=[c.name for c in checks if c.status is CheckStatus.NOT_PERFORMED],
            not_applicable=[c.name for c in checks if c.status is CheckStatus.NOT_APPLICABLE],
        ),
        requirements=requirements,
        checks=checks,
    )


def run_image_qa(
    image_bytes: bytes,
    requirements: ImageQARequirements,
    *,
    analyzers: Mapping[str, SemanticAnalyzer] | None = None,
    now: datetime | None = None,
) -> ImageQAResult:
    analyzers = analyzers or {}
    decoded: DecodedImage | None = None
    error: ImageDecodeError | None = None
    try:
        decoded = decode_for_qa(image_bytes)
    except ImageDecodeError as exc:
        error = exc

    checks: list[ImageQACheck] = [image_integrity_check(decoded, error)]
    if decoded is not None:
        checks += [
            aspect_ratio_check(decoded, requirements),
            brand_palette_check(decoded, requirements),
            negative_space_check(decoded, requirements),
        ]
    else:
        reason = "image_not_decodable" if error and error.is_defect else "analysis_limits_exceeded"
        for name, kind, severity, method in _IMPLEMENTED[1:]:
            checks.append(
                not_performed(name, kind, severity, method, reason, "Not checked: the image could not be analyzed.")
            )
    checks += [_run_semantic(name, decoded, requirements, analyzers) for name in SEMANTIC_CHECKS]
    return summarize(checks, requirements, now=now)


def unavailable_result(
    requirements: ImageQARequirements, *, reason: str, detail: str | None = None, now: datetime | None = None
) -> ImageQAResult:
    """QA could not obtain the artifact (expired URL, network error, ...): every
    check is NOT_PERFORMED. Never a pass, and never a block — an infrastructure
    problem must not reject a candidate."""
    evidence = {"fetch_error": detail} if detail else {}
    checks = [
        not_performed(
            name, kind, severity, method, reason, "Not checked: the generated image could not be retrieved.", evidence
        )
        for name, kind, severity, method in _IMPLEMENTED
    ]
    checks += [_semantic_placeholder(name) for name in SEMANTIC_CHECKS]
    return summarize(checks, requirements, now=now)
