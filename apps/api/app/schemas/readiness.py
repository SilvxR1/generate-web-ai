from pydantic import BaseModel, ConfigDict


class ProductionReadinessCheck(BaseModel):
    """One line of a business's production-readiness checklist. `blocking`
    is true only for a genuine technical blocker — something that will
    actually make publishing fail (no website configuration to publish,
    the hosting provider not configured on this server). Every other
    check (legal profile completeness, a custom domain, prior
    publication) is informational: `blocking` is always false for those,
    per P0's explicit "only real technical blockers should prevent
    publishing... do NOT invent legal blocking rules" constraint."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    ready: bool
    blocking: bool
    detail: str


class ProductionReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[ProductionReadinessCheck]
    # True only when at least one `blocking` check isn't ready — never
    # derived from an informational check, however incomplete.
    has_blocking_issues: bool
