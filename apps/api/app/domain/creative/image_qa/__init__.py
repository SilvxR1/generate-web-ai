"""Image QA (P2.7): post-generation quality checks on a generated image.
See docs/p2-7-visual-qa.md. Not the same as app.creative.frontend_engine.visual_qa
(browser QA of generated website drafts)."""

from app.domain.creative.image_qa.models import (
    IMAGE_QA_VERSION,
    CheckKind,
    CheckSeverity,
    CheckStatus,
    ImageQACheck,
    ImageQARequirements,
    ImageQAResult,
    direction_is_approval_eligible,
)
from app.domain.creative.image_qa.runner import (
    SemanticAnalyzer,
    requirements_from_provenance,
    run_image_qa,
    unavailable_result,
)

__all__ = [
    "IMAGE_QA_VERSION",
    "CheckKind",
    "CheckSeverity",
    "CheckStatus",
    "ImageQACheck",
    "ImageQARequirements",
    "ImageQAResult",
    "SemanticAnalyzer",
    "direction_is_approval_eligible",
    "requirements_from_provenance",
    "run_image_qa",
    "unavailable_result",
]
