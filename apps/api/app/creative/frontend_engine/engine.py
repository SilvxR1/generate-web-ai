"""FrontendEngineer — the P2 Part A boundary: turns a selected
CreativeDirection into real, bespoke frontend source code (never a
SiteConfig, never a block/design-family selection — see
app.domain.creative.direction's own docstring on why CreativeDirection
itself is free-text intent, not a template pick). Mirrors every other
provider-neutral ABC in this codebase (CreativeProvider,
CreativeDirectorProvider, BusinessAnalyzer): one boundary, one or more
swappable implementations. `AnthropicFrontendEngine`
(app.creative.frontend_engine.anthropic_engine) is the first,
replaceable implementation — nothing outside that module should need to
know Claude/Anthropic is involved.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.domain.business_config import BusinessConfig
from app.domain.creative import CreativeBriefAsset
from app.domain.creative.direction import CreativeDirection
from app.publishing.publisher import WebsiteArtifact


class FrontendEngineResult(BaseModel):
    """What every FrontendEngineer.generate() call returns — the
    transient build output (`artifact`, the same shape
    app.publishing.build.build_site returns for the deterministic
    engine) plus everything app.db.models.generative_website_artifact.
    GenerativeWebsiteArtifact needs to persist a durable, inspectable
    record of how it was produced."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    artifact: WebsiteArtifact
    framework: str = "astro"
    workspace_key: str
    build_command: str
    output_dir: str
    dependencies: list[str]
    generator_provider: str
    generator_model: str | None = None
    duration_ms: int
    notes: str = ""


class FrontendEngineer(ABC):
    name: ClassVar[str]

    @abstractmethod
    def generate(
        self,
        *,
        business_config: BusinessConfig,
        creative_direction: CreativeDirection,
        assets: Sequence[CreativeBriefAsset],
        platform_contract_version: str,
        business_id: str,
        api_base_url: str | None = None,
    ) -> FrontendEngineResult:
        """`business_config` is the sole source of factual claims (never
        `creative_direction`, which carries only intent — see
        CreativeDirection.constraints for the explicit allow/forbid
        boundary this call must respect); `assets` are the business's
        real, already-uploaded media; `business_id`/`api_base_url` are
        injected into the build's platform-config script tag by the
        engine itself, never trusted from generated content (see
        app.creative.frontend_engine.build's own docstring). Must raise
        (never return a fabricated success) on any workspace-security,
        dependency-policy, or build failure — P2.14's "generative failure
        never silently becomes deterministic success" is enforced by the
        caller never catching these and falling back, not by this method
        pretending to succeed.
        """
