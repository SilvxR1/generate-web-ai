"""Provider-independent validation of a generated creative asset (P2.2).

Deliberately metadata-only: it checks what can be reliably known from the
generation context and the provider's own result (a result exists, is a
valid https reference, has an expected media type and count, the provider
completed, dimensions/aspect ratio when reported, and that the spec that
requested it is intact). It does NOT and cannot detect unwanted text, logo
distortion, brand drift, composition problems or visual artifacts — those
are listed in `NOT_COVERED_BY_METADATA_VALIDATION` and reported as
`visual_qa: "not_performed"` on every result so a PASSED status is never
mistaken for "the image looks right". Future visual QA plugs in behind
`GeneratedAssetValidator` without changing callers.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.spec import CreativeGenerationSpec

NOT_COVERED_BY_METADATA_VALIDATION: tuple[str, ...] = (
    "unwanted_text",
    "logo_distortion",
    "brand_drift",
    "composition_quality",
    "visual_artifacts",
)

_ASPECT_TOLERANCE = 0.02


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class GeneratedAssetInfo:
    """What a provider adapter reports about one finished generation —
    provider-neutral; never carries credentials."""

    provider_completed: bool
    result_urls: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    job_id: str | None = None
    model: str | None = None


class ValidationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # None means the check could not be evaluated from available metadata
    # (skipped) — never treated as a pass or a failure.
    passed: bool | None
    detail: str | None = None


class AssetValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    checks: list[ValidationCheck] = Field(default_factory=list)
    visual_qa: str = "not_performed"
    not_covered: list[str] = Field(default_factory=lambda: list(NOT_COVERED_BY_METADATA_VALIDATION))


class GeneratedAssetValidator(Protocol):
    def validate(self, spec: CreativeGenerationSpec, generated: GeneratedAssetInfo) -> AssetValidationResult: ...


def _media_type_from_url(url: str) -> str | None:
    last_segment = urlparse(url).path.lower().rsplit("/", 1)[-1]
    if "." not in last_segment:
        return None
    return last_segment.rsplit(".", 1)[-1]


def _ratio(text: str) -> float | None:
    try:
        left, right = text.split(":")
        return int(left) / int(right)
    except (ValueError, ZeroDivisionError):
        return None


def _is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _media_type_allowed(media: str, allowed: tuple[str, ...]) -> bool:
    return media in allowed or (media == "jpeg" and "jpg" in allowed)


class MetadataAssetValidator:
    def validate(self, spec: CreativeGenerationSpec, generated: GeneratedAssetInfo) -> AssetValidationResult:
        urls = generated.result_urls
        checks: list[ValidationCheck] = [
            ValidationCheck(name="provider_completed", passed=generated.provider_completed),
            ValidationCheck(name="result_exists", passed=bool(urls)),
            ValidationCheck(
                name="provider_identity_recorded",
                passed=bool(generated.job_id and generated.model),
                detail="job id and model must be preserved for provenance",
            ),
            ValidationCheck(
                name="expected_output_count",
                passed=len(urls) == spec.output.num_outputs,
                detail=f"expected {spec.output.num_outputs}, got {len(urls)}",
            ),
            ValidationCheck(
                name="result_url_valid",
                passed=bool(urls) and all(_is_https_url(url) for url in urls),
                detail="result reference must be an https URL",
            ),
        ]

        media_types = [_media_type_from_url(url) for url in urls]
        if not media_types or any(media is None for media in media_types):
            checks.append(ValidationCheck(name="expected_media_type", passed=None, detail="media type not derivable"))
        else:
            checks.append(
                ValidationCheck(
                    name="expected_media_type",
                    passed=all(_media_type_allowed(str(media), spec.output.media_types) for media in media_types),
                    detail=f"expected one of {', '.join(spec.output.media_types)}",
                )
            )

        expected_ratio = _ratio(spec.output.aspect_ratio)
        if generated.width and generated.height and expected_ratio:
            actual = generated.width / generated.height
            checks.append(
                ValidationCheck(
                    name="aspect_ratio",
                    passed=abs(actual - expected_ratio) / expected_ratio <= _ASPECT_TOLERANCE,
                    detail=f"expected {spec.output.aspect_ratio}, got {generated.width}x{generated.height}",
                )
            )
        else:
            checks.append(ValidationCheck(name="aspect_ratio", passed=None, detail="dimensions not reported"))

        failed = any(check.passed is False for check in checks)
        return AssetValidationResult(
            status=ValidationStatus.FAILED if failed else ValidationStatus.PASSED, checks=checks
        )
