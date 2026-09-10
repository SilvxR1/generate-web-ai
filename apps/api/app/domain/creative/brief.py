"""CreativeBrief — the structured, provider-neutral input to a
CreativeProvider (app.creative.provider). Assembled from a business's
*persisted* BusinessConfig plus its *real* assets and reviews, never from
free-standing prose — every CreativeProvider implementation (internal or
Higgsfield) reads this shape, never BusinessConfig or the ORM directly, so
none of them ever need to know how a Business is actually stored.

Pure domain data: no FastAPI, no SQLAlchemy, no provider SDKs (Section 2's
boundary, same as app.domain.business_config). `AssetInput`/`ReviewInput`
below are Protocols, not imports of app.db.models — the caller
(app.creative.orchestrator, which does touch persistence) passes real
BusinessAsset/BusinessReview rows in directly; they satisfy these
Protocols structurally without this module ever importing SQLAlchemy.
"""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config import BrandColors, BrandTypography, BusinessConfig, Location, ServiceOffering
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    BrandStrategy,
    CreativeLevel,
    LeadSource,
)


class AssetInput(Protocol):
    """Structural shape app.db.models.business_asset.BusinessAsset already
    satisfies — see this module's own docstring for why a Protocol, not an
    import, defines the boundary."""

    id: UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    storage_url: str
    alt_text: str | None


class ReviewInput(Protocol):
    """Structural shape app.db.models.business_review.BusinessReview
    already satisfies. Only `body` (and, for future rating-weighted
    insight extraction, `rating`) is read — never `author_name` or
    anything else identifying, since CreativeBrief.customer_insights is a
    summary of *perceptions*, not a review-by-review dossier."""

    body: str
    rating: int | None


class CreativeBriefAsset(BaseModel):
    """One real or generated asset, as CreativeBrief exposes it to a
    provider — narrower than the full BusinessAsset row (no tenant_id, no
    raw metadata): a provider needs to know what an asset shows and where
    it lives, nothing about this codebase's own persistence."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    url: str
    alt_text: str | None = None


# A small, fixed taxonomy of customer-perception labels and the literal,
# lowercase phrases in real review text that support each one. Section 4
# explicitly allows this kind of extraction ("Business Analyzer should
# eventually be able to extract recurring customer perceptions") while
# forbidding fabrication — plain substring matching over real,
# already-imported review bodies satisfies both: every label surfaced here
# is directly traceable to phrases a real customer actually wrote, and a
# review's own text is never altered to produce it. This is a v1 heuristic,
# not an LLM analyzer — deliberately, per Section 20's "do not overbuild":
# it's a placeholder for a future AI-based BusinessAnalyzer pass (mirroring
# BusinessAnalyzer's own ABC + swappable-implementation shape) that reads
# the same BusinessReview rows, not a rewrite of this function's callers.
_INSIGHT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cleanliness": ("clean", "tidy", "spotless"),
    "reliability": ("on time", "on schedule", "reliable", "dependable", "punctual"),
    "transparent_pricing": ("fair price", "no hidden", "transparent pricing", "quote didn't change", "as quoted"),
    "communication": ("kept us informed", "great communication", "responsive", "informed us"),
    "quality_of_work": ("high quality", "excellent work", "great quality", "craftsmanship", "attention to detail"),
    "friendliness": ("friendly", "polite", "courteous"),
    "value_for_money": ("good value", "worth it", "value for money"),
}


def extract_customer_insights(reviews: Sequence[ReviewInput]) -> list[str]:
    """Recurring customer perceptions (Section 4), ordered by how many
    distinct reviews support each one, most-supported first. Returns an
    empty list rather than guessing when there are no reviews yet — never
    a substitute for the reviews themselves, which CreativeBrief does not
    carry verbatim (a provider gets insights, not a review dossier)."""
    counts: dict[str, int] = {}
    for review in reviews:
        body_lower = review.body.lower()
        for label, phrases in _INSIGHT_KEYWORDS.items():
            if any(phrase in body_lower for phrase in phrases):
                counts[label] = counts.get(label, 0) + 1
    return [label for label, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def _conversion_objective(config: BusinessConfig) -> str:
    """A simple, derived signal — not a field BusinessConfig stores
    directly (Section 6 lists "primary conversion goal" as Business
    Analyzer output; nothing produces that free-form judgment yet). Reads
    the one concrete fact this codebase already tracks: whether lead
    capture is enabled at all."""
    return "lead_capture" if config.automation.lead_capture else "brand_awareness"


def _recommended_sections(
    config: BusinessConfig, *, has_reviews: bool, assets: Sequence[CreativeBriefAsset]
) -> list[str]:
    """A provider-facing recommendation, not the internal deterministic
    generator's own block list (packages/website-generator/src/blocks.ts
    owns that independently and is not driven by this function) — a
    premium provider has no access to that TypeScript module, so this
    gives it an equivalent, data-driven starting point without
    duplicating its logic verbatim."""
    profile = config.business_profile
    sections = ["hero"]
    if profile.services:
        sections.append("services")
    if profile.description:
        sections.append("about")
    if any(asset.category in (AssetCategory.GALLERY, AssetCategory.PROJECT) for asset in assets):
        sections.append("gallery")
    if has_reviews:
        sections.append("testimonials")
    sections.append("cta")
    if profile.contact or LeadSource.WEBSITE_FORM in config.lead_management.sources:
        sections.append("contact")
    return sections


_ANIMATION_LEVEL_BY_CREATIVE_LEVEL: dict[CreativeLevel, str] = {
    CreativeLevel.BASIC: "minimal",
    CreativeLevel.PROFESSIONAL: "moderate",
    CreativeLevel.PREMIUM: "rich",
    CreativeLevel.CINEMATIC: "cinematic",
}


class CreativeBrief(BaseModel):
    """Everything a CreativeProvider needs to generate a website/visual
    experience for one business, with no dependency on how this codebase
    stores that business. Built once per generation request by
    build_creative_brief below — never hand-assembled by a provider or
    the orchestrator.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    business_name: str
    tagline: str | None = None
    industry: str
    description: str | None = None
    location: Location | None = None

    # Audience / objective
    target_customer: str | None = None
    conversion_objective: str

    # Offering
    services: list[ServiceOffering] = Field(default_factory=list)
    # Section 6 lists "differentiators" as future Business Analyzer
    # output — nothing derives them from real data yet, so this stays
    # empty rather than inventing claims about the business (never
    # populated with anything not traceable to a real, structured source).
    differentiators: list[str] = Field(default_factory=list)

    # Brand
    brand_strategy: BrandStrategy
    creative_level: CreativeLevel
    brand_colors: BrandColors | None = None
    typography: BrandTypography | None = None
    visual_style: str | None = None
    logo_url: str | None = None

    # Real + generated assets already on file (Section 1: real content is
    # preferred by construction — build_creative_brief below includes
    # every asset regardless of origin, but each carries its own `origin`
    # so a provider can itself prefer UPLOADED/IMPORTED over GENERATED for
    # the same category, and never needs to guess which is which).
    available_assets: list[CreativeBriefAsset] = Field(default_factory=list)

    # Real customer perceptions only (Section 4) — never the reviews
    # themselves, and never fabricated when there are none yet.
    customer_insights: list[str] = Field(default_factory=list)

    # Generation shape
    required_pages: list[str] = Field(default_factory=lambda: ["/"])
    required_sections: list[str] = Field(default_factory=list)
    animation_level: str = "minimal"
    media_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


def build_creative_brief(
    *,
    business_config: BusinessConfig,
    assets: Sequence[AssetInput] = (),
    reviews: Sequence[ReviewInput] = (),
) -> CreativeBrief:
    """The one place a CreativeBrief is assembled — deterministic, no AI
    call (mirrors packages/website-generator's generateSiteConfig: a fixed
    mapping from real, already-validated facts, not a second generation
    step of its own). `assets`/`reviews` are the business's *persisted*
    rows (via app.repositories.business_asset/business_review), passed in
    by the caller rather than fetched here — this function touches no
    session, no database.
    """
    profile = business_config.business_profile
    brand = business_config.brand
    creative = business_config.creative

    brief_assets = [
        CreativeBriefAsset(
            id=asset.id,
            kind=asset.kind,
            category=asset.category,
            origin=asset.origin,
            url=asset.storage_url,
            alt_text=asset.alt_text,
        )
        for asset in assets
    ]
    has_hero_candidate = any(asset.category == AssetCategory.HERO_CANDIDATE for asset in brief_assets)
    media_requirements: list[str] = []
    if creative.level is not CreativeLevel.BASIC and not has_hero_candidate:
        media_requirements.append("hero_image")

    return CreativeBrief(
        business_name=profile.name,
        tagline=brand.tagline if brand else None,
        industry=profile.industry.value,
        description=profile.description,
        location=profile.location,
        target_customer=profile.target_customers,
        conversion_objective=_conversion_objective(business_config),
        services=profile.services,
        brand_strategy=creative.strategy,
        creative_level=creative.level,
        brand_colors=brand.colors if brand else None,
        typography=brand.typography if brand else None,
        visual_style=brand.visual_style if brand else None,
        logo_url=brand.logo.url if brand and brand.logo else None,
        available_assets=brief_assets,
        customer_insights=extract_customer_insights(reviews),
        required_sections=_recommended_sections(business_config, has_reviews=bool(reviews), assets=brief_assets),
        animation_level=_ANIMATION_LEVEL_BY_CREATIVE_LEVEL[creative.level],
        media_requirements=media_requirements,
    )
