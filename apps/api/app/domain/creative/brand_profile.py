"""BrandVisualProfile (P2.3) — a provider-independent description of a
business's visual identity that lets prompt composition communicate
identity *as text*, so an authoritative logo never has to be sent to an
image model just to convey palette or style.

Why this exists: two real production generations (P2.1 and P2.2) showed a
reference-conditioned model treats a supplied logo as the thing to
reproduce, whatever the prompt says. Identity guidance therefore has to
reach the model without the logo image itself.

HONESTY RULE: the profile holds only what can be obtained reliably today —
structured brand configuration (colors, visual style, typography) and the
ids of the official-logo assets it was derived from. There is no image
understanding in this backend, so `geometry` and `mood` stay empty and
`semantic_analysis` is always "not_performed"; nothing here infers
"playful", "luxury" or "handmade" from pixels. Deterministic palette
extraction from logo bytes is a designed-for seam (`asset_palettes`, source
`ASSET_EXTRACTION`) but is not wired in this version: it needs an image
library and a storage read in the request path — see
docs/p2-3-brand-reference-model-routing.md.
"""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin

BRAND_PROFILE_VERSION = "p2.3-v1"

SOURCE_OFFICIAL_LOGO = "official_logo"
SOURCE_BRAND_COLORS = "brand_config_colors"
SOURCE_BRAND_STYLE = "brand_config_style"
SOURCE_BRAND_TYPOGRAPHY = "brand_config_typography"
SOURCE_LOGO_PALETTE = "official_logo_palette"

_MAX_LOGO_SOURCES = 2
# Palette values are interpolated into prompts, so accept only plain color
# notations (hex, named, rgb()/hsl()/oklch()) — never free text.
_SAFE_COLOR = re.compile(r"^[#A-Za-z0-9 (),.%/-]{1,40}$")


class PaletteSource(StrEnum):
    BRAND_CONFIG = "brand_config"
    # Reserved: no extractor is wired in this version.
    ASSET_EXTRACTION = "asset_extraction"


class PaletteColor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    role: str
    source: PaletteSource


class BrandVisualProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = BRAND_PROFILE_VERSION
    palette: list[PaletteColor] = Field(default_factory=list)
    # Only ever populated from a reliable source; empty today.
    geometry: list[str] = Field(default_factory=list)
    visual_style: str | None = None
    mood: list[str] = Field(default_factory=list)
    # Known-from-config hints for the website layer. Deliberately never
    # used in image prompts (generated imagery carries no text).
    typography_hints: list[str] = Field(default_factory=list)
    # Assets this profile was derived from (authoritative brand sources).
    # These informed the profile; they were NOT necessarily sent to any
    # image model — provenance records that separately.
    source_asset_ids: list[UUID] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    has_official_logo: bool = False
    semantic_analysis: str = "not_performed"


def is_official_logo(asset: CreativeBriefAsset) -> bool:
    """A real, business-provided logo. A generated asset is never the
    official logo, whatever it is labelled."""
    if asset.origin is AssetOrigin.GENERATED:
        return False
    return asset.kind is AssetKind.LOGO or asset.category is AssetCategory.LOGO


def _safe_color(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if _SAFE_COLOR.match(cleaned) else None


def build_brand_visual_profile(
    brief: CreativeBrief,
    assets: Sequence[CreativeBriefAsset],
    *,
    asset_palettes: Mapping[UUID, Sequence[str]] | None = None,
) -> BrandVisualProfile:
    """Deterministic and side-effect free. `asset_palettes` (logo asset id ->
    dominant colors) is the seam for a future palette extractor; callers
    that have none simply omit it."""
    sources: list[str] = []
    palette: list[PaletteColor] = []

    if brief.brand_colors is not None:
        for role in ("primary", "secondary", "accent"):
            color = _safe_color(getattr(brief.brand_colors, role))
            if color:
                palette.append(PaletteColor(value=color, role=role, source=PaletteSource.BRAND_CONFIG))
        if palette:
            sources.append(SOURCE_BRAND_COLORS)

    logos = [asset for asset in assets if is_official_logo(asset)][:_MAX_LOGO_SOURCES]
    if logos:
        sources.append(SOURCE_OFFICIAL_LOGO)

    extracted = False
    seen = {color.value.lower() for color in palette}
    for logo in logos:
        for value in (asset_palettes or {}).get(logo.id, ()):
            color = _safe_color(value)
            if color and color.lower() not in seen:
                palette.append(PaletteColor(value=color, role="dominant", source=PaletteSource.ASSET_EXTRACTION))
                seen.add(color.lower())
                extracted = True
    if extracted:
        sources.append(SOURCE_LOGO_PALETTE)

    visual_style = brief.visual_style.strip() if brief.visual_style and brief.visual_style.strip() else None
    if visual_style:
        sources.append(SOURCE_BRAND_STYLE)

    typography_hints: list[str] = []
    if brief.typography is not None:
        if brief.typography.display:
            typography_hints.append(f"display: {brief.typography.display}")
        typography_hints.append(f"body: {brief.typography.sans}")
        sources.append(SOURCE_BRAND_TYPOGRAPHY)

    return BrandVisualProfile(
        palette=palette,
        visual_style=visual_style,
        typography_hints=typography_hints,
        source_asset_ids=[logo.id for logo in logos],
        sources=sources,
        has_official_logo=bool(logos),
    )
