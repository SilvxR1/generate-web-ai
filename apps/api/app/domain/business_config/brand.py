"""BrandConfig — declarative visual identity, no arbitrary CSS.

Mirrors packages/site-config's ThemeColorConfig/ThemeFontConfig/
BrandConfig field-for-field (see packages/site-config/src/theme.ts and
brand.ts) so the same brand data is expressible on both sides of the
Python/TypeScript boundary, even though nothing auto-converts between
them yet (see WebsiteConfig's docstring in website.py for why that
conversion is future work, not this phase's job).
"""

from pydantic import BaseModel, ConfigDict, Field


class AssetRef(BaseModel):
    """A referenced image (logo, brand asset). `url` is a plain string —
    not a strict URL type — because nothing generates or validates real
    asset URLs yet (no upload pipeline exists); over-constraining this
    before that exists would just make the schema harder to fill in for
    no real benefit. `alt` is required so nothing built from this is
    inaccessible by construction, matching AssetConfig's own rule in
    packages/site-config."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    alt: str = Field(min_length=1, max_length=300)


class BrandColors(BaseModel):
    """Mirrors ThemeColorConfig exactly. Deliberately not restricted to
    hex-only — Tailwind v4 (this repo's styling layer) accepts named
    colors, rgb()/hsl()/oklch(), etc., and the TypeScript type this
    mirrors never restricted the format either."""

    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1)
    secondary: str = Field(min_length=1)
    accent: str = Field(min_length=1)
    background: str = Field(min_length=1)
    foreground: str = Field(min_length=1)


class BrandTypography(BaseModel):
    """Mirrors ThemeFontConfig: `sans` required, `display` optional
    (falls back to `sans` when omitted, same as the TypeScript side)."""

    model_config = ConfigDict(extra="forbid")

    sans: str = Field(min_length=1)
    display: str | None = None


class BrandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo: AssetRef | None = None
    tagline: str | None = Field(default=None, max_length=200)
    colors: BrandColors
    typography: BrandTypography
    # Free-text descriptor (e.g. "minimal", "warm and editorial") — no
    # controlled vocabulary yet; Section 6 explicitly warns against
    # over-architecting this before real usage shows what values recur.
    visual_style: str | None = Field(default=None, max_length=100)
    assets: list[AssetRef] = Field(default_factory=list)
