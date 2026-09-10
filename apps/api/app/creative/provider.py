"""CreativeProvider — the provider-neutral interface between a
CreativeBrief (app.domain.creative) and whatever actually produces
creative output (design, imagery, video, other visual assets). Mirrors
app.analysis.analyzer.BusinessAnalyzer and
app.publishing.publisher.WebsitePublisher's exact shape: an ABC plus one
or more swappable concrete implementations
(app.creative.internal.InternalCreativeProvider,
app.creative.higgsfield.provider.HiggsfieldCreativeProvider), so
app.creative.orchestrator never needs to know which provider it's
actually calling.
"""

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative import CreativeBrief
from app.domain.enums import AssetKind, CreativeGenerationStatus, CreativeGenerationType, CreativeProviderName


class CreativeAsset(BaseModel):
    """One piece of output a generation produced — provider-neutral, no
    credential, no provider-specific payload. `url` is None when a
    provider only returns an opaque `external_reference` (e.g. a job id a
    caller must poll or fetch later) rather than an immediately
    fetchable asset."""

    model_config = ConfigDict(extra="forbid")

    kind: AssetKind
    url: str | None = None
    external_reference: str | None = None
    metadata: dict = Field(default_factory=dict)


class CreativeGenerationResult(BaseModel):
    """What every CreativeProvider method returns — normalized the same
    way regardless of which provider produced it, so
    app.creative.orchestrator can persist a CreativeGeneration row
    without any provider-specific branching. `credits_used`/
    `estimated_cost` stay None unless the provider actually reports them
    (Section 13 of the master context: never invent costs)."""

    model_config = ConfigDict(extra="forbid")

    status: CreativeGenerationStatus
    assets: list[CreativeAsset] = Field(default_factory=list)
    external_reference: str | None = None
    credits_used: float | None = None
    estimated_cost: float | None = None
    raw_metadata: dict = Field(default_factory=dict)


class CreativeProvider(ABC):
    name: ClassVar[CreativeProviderName]
    capabilities: ClassVar[frozenset[CreativeGenerationType]]

    def supports(self, generation_type: CreativeGenerationType) -> bool:
        return generation_type in self.capabilities

    @abstractmethod
    def generate_concept(self, brief: CreativeBrief) -> CreativeGenerationResult:
        """A cheap, early-stage art-direction pass (palette, typography,
        layout direction) — no final assets, never a substitute for
        generate_website."""

    @abstractmethod
    def generate_website(self, brief: CreativeBrief) -> CreativeGenerationResult: ...

    @abstractmethod
    def generate_image(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult: ...

    @abstractmethod
    def generate_video(self, brief: CreativeBrief, *, prompt_hint: str | None = None) -> CreativeGenerationResult: ...

    @abstractmethod
    def generate_visual_asset(
        self, brief: CreativeBrief, *, prompt_hint: str | None = None
    ) -> CreativeGenerationResult: ...
