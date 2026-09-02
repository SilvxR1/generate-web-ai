"""WebsiteConfig — business-level INTENT/preferences for the generated
website, not the generated content itself.

The actual page/block content (hero copy, gallery items, FAQ entries...)
is packages/site-config's SiteConfig (TypeScript, zero Astro dependency,
consumed by the Astro renderer) — already a complete, working "website
engine" schema. Mirroring its full block-content tree here would be
exactly the `BusinessConfig.website_v2` duplication the brief explicitly
rules out, for a shape nothing populates yet (no generator exists that
turns BusinessConfig into a SiteConfig — that's future work). This stays
intentionally thin: whether a website exists and a few generation-level
preferences. The generated SiteConfig itself is persisted separately, on
the existing Website.config JSON column (app.db.models.website), once
something actually produces it.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_config.brand import AssetRef


class SEOPreferences(BaseModel):
    """Mirrors packages/site-config's SEOConfig (title/description/
    ogImage) — the site-wide default a generator would carry over."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    og_image: AssetRef | None = None


class WebsiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # A Template.id (app.db.models.template) or other named starting
    # point, once template selection exists. Free string for now — no
    # FK validated here, since BusinessConfig must not depend on the
    # persistence layer (Section 2).
    template_preference: str | None = Field(default=None, max_length=200)
    seo: SEOPreferences | None = None
