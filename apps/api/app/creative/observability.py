"""log_pipeline_stage — the P2 observability primitive for the generative
pipeline (P2 Part J). This codebase has no metrics/observability stack
today (see app.logging_config's own docstring: "deliberately not a full
structured-JSON/observability stack... yet" — the only prior use of
`logging` anywhere in this backend is app.errors's unhandled-exception
handler), so this is a small, structured extension of the existing
plain-`logging` convention rather than a new Prometheus/metrics system —
following P2's own "do not over-engineer" instruction and "follow
existing observability conventions" rather than the literal example
names in the task brief.

Every call logs one line with a fixed set of fields (business_id,
provider, stage, duration_ms, result) at INFO (success) or WARNING
(failure) — never a lead/customer PII field, never a credential. A
caller that wants real metrics later (counters/histograms) can parse
these structured lines or replace this function's body with a real
metrics client without changing any call site.
"""

import logging
from time import monotonic
from uuid import UUID

logger = logging.getLogger("app.creative.pipeline")


def log_pipeline_stage(
    *,
    stage: str,
    business_id: UUID | str,
    provider: str,
    duration_ms: float | None = None,
    result: str,
    **extra: str | int | float | bool | None,
) -> None:
    """`stage` is one of: create_directions, develop_direction,
    frontend_generate, generative_build, platform_contract,
    generative_publish. `result` is one of: success, failure,
    budget_exceeded. `extra` may carry non-PII counters (e.g.
    credits_used, candidate_count) — never a name/email/phone/message."""
    payload = {
        "stage": stage,
        "business_id": str(business_id),
        "provider": provider,
        "duration_ms": duration_ms,
        "result": result,
        **extra,
    }
    level = logging.INFO if result == "success" else logging.WARNING
    logger.log(level, "creative_pipeline_stage", extra={"pipeline": payload})


class StageTimer:
    """`with StageTimer(...) as timer:` measures wall-clock duration and
    logs exactly once on exit — success unless `timer.mark_failure(...)`
    was called inside the block, so a raised exception still logs a
    failure line (with no leaked exception message, which could carry
    provider response text) before propagating."""

    def __init__(
        self, *, stage: str, business_id: UUID | str, provider: str, **extra: str | int | float | bool | None
    ) -> None:
        self._stage = stage
        self._business_id = business_id
        self._provider = provider
        self._extra = extra
        self._result = "success"
        self._started = 0.0

    def mark_failure(self, result: str = "failure") -> None:
        self._result = result

    def __enter__(self) -> "StageTimer":
        self._started = monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None and self._result == "success":
            self._result = "failure"
        duration_ms = (monotonic() - self._started) * 1000
        log_pipeline_stage(
            stage=self._stage,
            business_id=self._business_id,
            provider=self._provider,
            duration_ms=round(duration_ms, 1),
            result=self._result,
            **self._extra,
        )
