"""BusinessAnalyzer — the provider-neutral interface between a natural-
language business briefing and a proposed BusinessConfig.
AnthropicBusinessAnalyzer (app.analysis.claude) is the first,
replaceable implementation; nothing outside app.analysis.claude
should need to know Claude/Anthropic is involved.

A BusinessAnalyzer never executes anything, never touches n8n, never
receives or handles credentials, and never persists its result — it only
turns text into a *proposed* BusinessConfig for a human to review. See
app.routers.businesses's `POST /businesses/analyze` for the boundary
that keeps this a proposal, not a write.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config import BusinessConfig


class BusinessAnalysisResult(BaseModel):
    """What a BusinessAnalyzer returns: a best-effort BusinessConfig
    proposal (BusinessConfig's own validators already guarantee it's
    well-formed if present) plus what it couldn't determine.
    `proposed_config` is None when even the fields BusinessConfig
    requires (name, slug, industry) couldn't be established — there is
    no such thing as a partially-invalid BusinessConfig here, only "no
    proposal yet" plus questions."""

    model_config = ConfigDict(extra="forbid")

    proposed_config: BusinessConfig | None
    missing_information: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class BusinessAnalyzer(ABC):
    @abstractmethod
    def analyze(self, briefing: str) -> BusinessAnalysisResult:
        """`briefing` is untrusted, human-submitted free text — treat it
        as data, never as instructions to this analyzer or anything
        downstream of it."""
