"""CreativeBudget — first-class credit-spend tracking for one
CreativeDirectorProvider workflow run (create_directions +
develop_direction, app.creative.director), per P2.3's "Credit control"
requirement. This is an internal spend ceiling, not a pricing plan sold
to a business.

`DEFAULT_TIER_LIMITS` gives STANDARD/PREMIUM a real target range and hard
limit; EXPERIMENTAL deliberately has none — a caller building a
CreativeBudget at that tier must pass `hard_limit` explicitly (enforced
by `CreativeBudget.for_tier` below), matching the task's "EXPERIMENTAL
configurable, hard limit must always be explicit" rule: there is no
implicit ceiling for a tier whose whole point is "we don't have a settled
number yet".

A budget never retroactively decides a call shouldn't have happened —
`record_spend` is called *before* the credit-consuming call is made, with
the *already-known* cost of that specific call (from a real
`higgsfield generate cost` estimate or the provider's own reported
spend), and raises before the call ever runs if it would push cumulative
spend over the hard limit. Nothing in this module invents a cost; a
provider that can't report one must ask for the estimate first (see
app.creative.higgsfield.director).
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.creative.errors import CreativeProviderError
from app.domain.enums import CreativeBudgetTier

# (target_min, target_max, hard_limit) — None hard_limit means "the
# caller must supply one explicitly", never "unlimited".
DEFAULT_TIER_LIMITS: dict[CreativeBudgetTier, tuple[float, float, float | None]] = {
    CreativeBudgetTier.STANDARD: (10.0, 15.0, 20.0),
    CreativeBudgetTier.PREMIUM: (20.0, 30.0, 50.0),
    CreativeBudgetTier.EXPERIMENTAL: (0.0, 0.0, None),
}


class BudgetExceededError(CreativeProviderError):
    """Raised by CreativeBudget.record_spend before a call that would push
    cumulative spend past `hard_limit` is ever made — the call itself
    never happens; this is a pre-flight refusal, not a post-hoc report of
    overspend."""


class CreativeBudgetCallRecord(BaseModel):
    """One accounted-for spend event — what P2.3's "persist enough
    metadata to understand: credits used, calls/generations, iterations,
    provider, model/tool where available, duration, success/failure"
    asks for, one row per call. `iteration` is the call's position within
    its own stage (e.g. the 2nd of 3 create_directions candidate calls),
    not a global counter."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    operation: str
    model: str | None = None
    iteration: int | None = None
    credits: float
    duration_ms: int | None = None
    success: bool = True
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CreativeBudget(BaseModel):
    """Mutable spend tracker threaded through one
    create_directions/develop_direction workflow call
    (app.creative.director_orchestrator) — the *same* instance is passed
    into every provider call in that workflow so cumulative spend is
    tracked across all of them, not reset per call."""

    model_config = ConfigDict(extra="forbid")

    tier: CreativeBudgetTier
    hard_limit: float
    target_min: float | None = None
    target_max: float | None = None
    credits_used: float = 0.0
    calls: list[CreativeBudgetCallRecord] = Field(default_factory=list)

    @classmethod
    def for_tier(cls, tier: CreativeBudgetTier, *, hard_limit: float | None = None) -> "CreativeBudget":
        target_min, target_max, default_hard_limit = DEFAULT_TIER_LIMITS[tier]
        resolved_hard_limit = hard_limit if hard_limit is not None else default_hard_limit
        if resolved_hard_limit is None:
            raise ValueError(
                f"CreativeBudgetTier.{tier.name} has no default hard limit — pass hard_limit explicitly."
            )
        return cls(tier=tier, hard_limit=resolved_hard_limit, target_min=target_min, target_max=target_max)

    def remaining(self) -> float:
        return max(self.hard_limit - self.credits_used, 0.0)

    def record_spend(
        self,
        credits: float,
        *,
        provider: str,
        operation: str,
        model: str | None = None,
        iteration: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Call *before* the credit-consuming operation runs, with its
        already-known cost. Raises BudgetExceededError — leaving
        `credits_used`/`calls` unchanged — if this spend would exceed
        `hard_limit`; only once the call is confirmed within budget does
        the caller actually invoke the provider and then this method
        records it as having happened."""
        if self.credits_used + credits > self.hard_limit:
            raise BudgetExceededError(
                f"Refusing to spend {credits} more Higgsfield credits: already used "
                f"{self.credits_used}/{self.hard_limit} ({self.tier.value} tier) for this generation."
            )
        self.credits_used += credits
        self.calls.append(
            CreativeBudgetCallRecord(
                provider=provider,
                operation=operation,
                model=model,
                iteration=iteration,
                credits=credits,
                duration_ms=duration_ms,
            )
        )

    def record_failure(
        self, *, provider: str, operation: str, model: str | None = None, iteration: int | None = None
    ) -> None:
        """A call that was attempted but failed before consuming credits
        (e.g. a CLI/network error) — recorded for observability
        (calls/iterations history) without affecting `credits_used`."""
        self.calls.append(
            CreativeBudgetCallRecord(
                provider=provider, operation=operation, model=model, iteration=iteration, credits=0.0, success=False
            )
        )
