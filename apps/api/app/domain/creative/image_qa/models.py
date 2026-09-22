"""Image QA domain model (P2.7) — provider-independent.

NOT to be confused with `app.creative.frontend_engine.visual_qa`, which is the
real-browser QA of generated WEBSITE DRAFTS. This package inspects the pixels of
a generated IMAGE (a hero, a background, ...) after a provider completed it.

The one rule this model exists to protect: **not checked is never passed.**
Every check reports exactly one of five statuses, and `not_performed` /
`not_applicable` are never folded into `pass`:

  pass            the check ran and the image satisfied it
  warning         the check ran and found something an operator should see
  fail            the check ran and found a defect (blocking only when the
                  check's policy severity is `blocking`)
  not_performed   the check could not / did not run (no analyzer, artifact
                  unavailable, analysis limits) — a COVERAGE GAP, made visible
  not_applicable  the contract has no such requirement (e.g. no brand palette)

`overall_status` summarizes only the checks that RAN; `coverage` states which
checks did not, so "pass" can never be read as "the image looks right".
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

IMAGE_QA_VERSION = "p2.7-v1"


class CheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    NOT_PERFORMED = "not_performed"
    NOT_APPLICABLE = "not_applicable"


class CheckKind(StrEnum):
    DETERMINISTIC = "deterministic"  # an exact property of the bytes / pixels
    HEURISTIC = "heuristic"  # a measurement plus a documented, tunable threshold
    SEMANTIC = "semantic"  # requires understanding image content (never inferred here)


class CheckSeverity(StrEnum):
    """What a non-passing result of this check DOES under the current policy."""

    BLOCKING = "blocking"  # a FAIL makes the candidate ineligible for recommendation/approval
    WARNING = "warning"  # visible to the operator, never blocks
    INFORMATIONAL = "informational"  # coverage information only


# Stable check names (provenance keys — never renamed lightly).
CHECK_IMAGE_INTEGRITY = "image_integrity"
CHECK_ASPECT_RATIO = "aspect_ratio"
CHECK_BRAND_PALETTE = "brand_palette_adherence"
CHECK_NEGATIVE_SPACE = "hero_negative_space"
# Semantic checks: NOT_PERFORMED until a SemanticAnalyzer is registered.
CHECK_UNWANTED_TEXT = "unwanted_text"
CHECK_INTERFACE_DETECTION = "interface_detection"
CHECK_UNWANTED_LOGO = "unwanted_logo"
CHECK_LOGO_DISTORTION = "logo_distortion"
CHECK_SUBJECT_CONSISTENCY = "subject_consistency"
# Semantic brand drift is NOT palette adherence: adherence measures pixels
# against a requested palette; drift would judge whether the image still
# "feels like" the brand. Only the former is implemented.
CHECK_BRAND_DRIFT = "brand_drift"
CHECK_VISUAL_ARTIFACTS = "visual_artifacts"

SEMANTIC_CHECKS: tuple[str, ...] = (
    CHECK_UNWANTED_TEXT,
    CHECK_INTERFACE_DETECTION,
    CHECK_UNWANTED_LOGO,
    CHECK_LOGO_DISTORTION,
    CHECK_SUBJECT_CONSISTENCY,
    CHECK_BRAND_DRIFT,
    CHECK_VISUAL_ARTIFACTS,
)


class ImageQARequirements(BaseModel):
    """The slice of the GenerationContract that a generated image can be
    checked against. Recorded on the result so it is always possible to say
    WHICH requirements were evaluated."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    aspect_ratio: str | None = None
    # Hex or configured color notations exactly as they reached the scene.
    brand_palette: tuple[str, ...] = ()
    # "right" | "left" | "center" | "none" | None — where the scene plan put the subject.
    subject_side: str | None = None
    purpose: str | None = None


class ImageQACheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: CheckStatus
    kind: CheckKind
    severity: CheckSeverity
    method: str
    version: str = IMAGE_QA_VERSION
    # A single derived number where one is meaningful — never the only output.
    score: float | None = None
    # One plain sentence that explains the status.
    summary: str
    # A stable code explaining not_performed / not_applicable.
    reason: str | None = None
    # Concise structured measurements — no pixel dumps, no URLs, no bytes.
    evidence: dict = Field(default_factory=dict)


class Coverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    performed: list[str] = Field(default_factory=list)
    not_performed: list[str] = Field(default_factory=list)
    not_applicable: list[str] = Field(default_factory=list)


class ImageQAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = IMAGE_QA_VERSION
    performed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Summary of the checks that RAN (see module docstring). not_performed when none ran.
    overall_status: CheckStatus
    # False only when a BLOCKING check failed. Generation itself stays `completed`:
    # a technically successful provider job is never rewritten as a provider failure.
    approval_eligible: bool = True
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    requirements: ImageQARequirements = Field(default_factory=ImageQARequirements)
    checks: list[ImageQACheck] = Field(default_factory=list)


def direction_is_approval_eligible(generation_metadata: dict | None) -> bool:
    """True unless Visual QA recorded a BLOCKING failure. A direction with no
    Visual QA record (older rows, internal-fallback directions with no image)
    is unaffected — absence of QA never blocks, and is never shown as a pass."""
    spec = (generation_metadata or {}).get("creative_spec")
    qa = spec.get("visual_qa") if isinstance(spec, dict) else None
    return not (isinstance(qa, dict) and qa.get("approval_eligible") is False)
