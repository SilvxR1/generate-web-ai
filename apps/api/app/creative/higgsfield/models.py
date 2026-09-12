"""Shared, provider-agnostic result shapes for both Higgsfield integration
paths (app.creative.higgsfield.cli.HiggsfieldCli and
app.creative.higgsfield.api_client.HiggsfieldApiClient) — kept in their own
module, not owned by either, so app.creative.higgsfield.director's shared
orchestration logic can depend on this shape without importing a
CLI-specific or REST-specific module."""

from dataclasses import dataclass, field


@dataclass
class HiggsfieldJobResult:
    job_id: str
    job_type: str
    status: str
    result_url: str | None
    raw: dict = field(default_factory=dict)
