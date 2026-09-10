"""CreativeConfig — a business's creative-generation intent/preferences:
how much of its existing visual identity to preserve, and how premium a
creative provider its generation requests should target. Mirrors
WebsiteConfig's own boundary (website.py's docstring): intent/preference
only, never the generated output itself — that lives on CreativeGeneration
rows (app.db.models.creative_generation) and the asset library
(app.db.models.business_asset), not here.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import BrandStrategy, CreativeLevel


class CreativeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: BrandStrategy = BrandStrategy.EVOLVE
    level: CreativeLevel = CreativeLevel.BASIC
    # A CreativeProviderName value, or None to let CreativeOrchestrator
    # choose based on `level` (app.creative.orchestrator.select_provider).
    # Free string rather than the enum itself so a config predating a
    # future provider's addition still deserializes without a migration —
    # same reasoning as WebsiteConfig.template_preference.
    preferred_provider: str | None = Field(default=None, max_length=50)
