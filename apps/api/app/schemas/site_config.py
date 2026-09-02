"""The request body for POST /businesses/{id}/website/publish: the exact
SiteConfig `generateSiteConfig()` (packages/website-generator, TypeScript)
already produced for Studio's own website preview
(apps/studio/.../PreviewStep.tsx) — Studio sends that same object back
here rather than this backend ever recomputing or re-deriving it, so the
published site can never drift from what the preview showed.

This model's whole job is a clean 422 for a structurally broken payload
before app.publishing.build spends a real `astro build` subprocess on
it — not reinterpreting the content. It's validated, then serialized
back to JSON and handed to that real Astro build verbatim (see
app.publishing.build.build_site), so nothing here needs to be strict
about content it doesn't itself read: `theme`/`seo`/`brand` are pinned
down because app.publishing.build's own Astro Layout consumes them
directly (a shape mismatch there fails obscurely deep inside the build,
not with a clear 422 here); block `content` stays a raw dict because
only the real @generate-web-ai/renderer/blocks package interprets it,
never this backend. `business`/`features` pass through opaque and
untouched — this backend has nothing to say about their shape either.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SiteBrandPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    tagline: str | None = None
    logo: dict[str, Any] | None = None


class SiteSEOPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    ogImage: dict[str, Any] | None = None  # noqa: N815 — mirrors the TS field name verbatim


class SiteThemeColorsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary: str = Field(min_length=1)
    secondary: str = Field(min_length=1)
    accent: str = Field(min_length=1)
    background: str = Field(min_length=1)
    foreground: str = Field(min_length=1)


class SiteThemeFontsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sans: str = Field(min_length=1)
    display: str | None = None


class SiteThemeRadiusPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base: str = Field(min_length=1)
    lg: str = Field(min_length=1)


class SiteThemePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    colors: SiteThemeColorsPayload
    fonts: SiteThemeFontsPayload
    radius: SiteThemeRadiusPayload


class SiteBlockPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    content: dict[str, Any] = Field(default_factory=dict)


class SitePagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    blocks: list[SiteBlockPayload] = Field(default_factory=list)


class SiteConfigPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brand: SiteBrandPayload
    theme: SiteThemePayload
    seo: SiteSEOPayload
    pages: list[SitePagePayload] = Field(min_length=1)
    # Opaque passthrough — see this module's docstring.
    business: dict[str, Any] | None = None
    features: dict[str, Any] | None = None
