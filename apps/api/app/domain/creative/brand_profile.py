"""BrandVisualProfile (P2.3) — a provider-independent description of a
business's visual identity that lets prompt composition communicate
identity *as text*, so an authoritative logo never has to be sent to an
image model just to convey palette or style.

Why this exists: two real production generations (P2.1 and P2.2) showed a
reference-conditioned model treats a supplied logo as the thing to
reproduce, whatever the prompt says. Identity guidance therefore has to
reach the model without the logo image itself.

HONESTY RULE: the profile holds only what can be obtained reliably —
structured brand configuration (colors, visual style, typography) and
colors MEASURED from the official logo (P2.6, app.domain.creative.
brand_intelligence). There is no semantic image understanding in this
backend, so `geometry` and `mood` stay empty and `semantic_analysis` is
always "not_performed"; nothing here infers "playful", "luxury" or
"handmade" from pixels.

SOURCE PRIORITY (P2.6): explicitly configured brand colors > colors measured
from an authoritative official logo > no value. Configured colors are never
mixed with measured ones, and a missing signal leaves the palette empty —
`palette_status` says WHY (configured / measured / unavailable /
not_performed / failed) so an empty palette is never ambiguous. Typography
and visual style come only from explicit configuration and are never
inferred from a logo's appearance.
"""

import re
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.creative.brand_intelligence import (
    MAX_PALETTE,
    ExcludedColor,
    MeasurementStatus,
)
from app.domain.creative.brief import CreativeBrief, CreativeBriefAsset
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin

BRAND_PROFILE_VERSION = "p2.6-v1"

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
    # Colors measured from an authoritative raster (the official logo).
    ASSET_EXTRACTION = "asset_extraction"


class PaletteStatus(StrEnum):
    """Why the palette is what it is — an empty palette is never ambiguous."""

    CONFIGURED = "configured"  # explicit brand colors exist and were used
    MEASURED = "measured"  # measured from an authoritative asset
    UNAVAILABLE = "unavailable"  # no defensible signal (no logo / no colors found)
    NOT_PERFORMED = "not_performed"  # a logo exists but no measurement was supplied
    FAILED = "failed"  # a measurement was attempted and could not be made


class PaletteColor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    role: str
    source: PaletteSource
    # Measured properties — present only for ASSET_EXTRACTION colors.
    source_asset_id: UUID | None = None
    foreground_share: float | None = None
    luminance: float | None = None
    tone: str | None = None
    saturation_band: str | None = None


class BrandVisualProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = BRAND_PROFILE_VERSION
    palette: list[PaletteColor] = Field(default_factory=list)
    palette_status: PaletteStatus = PaletteStatus.NOT_PERFORMED
    # Measurement provenance (None unless a palette was measured / failed).
    palette_method: str | None = None
    analysis_version: str | None = None
    analysis_failure: str | None = None
    measured_asset_ids: list[UUID] = Field(default_factory=list)
    # Colors seen in the logo but deliberately NOT used (background, neutrals).
    excluded_colors: list[ExcludedColor] = Field(default_factory=list)
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


def official_logos(assets: Sequence[CreativeBriefAsset]) -> list[CreativeBriefAsset]:
    """The authoritative logo sources (bounded). The ONE selection rule shared
    by the profile builder and the measurement service, so what is measured is
    exactly what the profile reads."""
    return [asset for asset in assets if is_official_logo(asset)][:_MAX_LOGO_SOURCES]


def _safe_color(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if _SAFE_COLOR.match(cleaned) else None


def _measured_palette(
    brief: CreativeBrief, logos: Sequence[CreativeBriefAsset]
) -> tuple[list[PaletteColor], PaletteStatus, dict]:
    """Colors from the brief's measurements of the CURRENT official logos.
    A measurement of any other asset (e.g. one that is no longer the logo) is
    ignored, so a stale measurement can never leak into a profile."""
    if not logos:
        return [], PaletteStatus.UNAVAILABLE, {}
    by_asset = {measurement.asset_id: measurement for measurement in brief.brand_measurements}
    attempted = [by_asset[logo.id] for logo in logos if logo.id in by_asset]
    if not attempted:
        return [], PaletteStatus.NOT_PERFORMED, {}

    palette: list[PaletteColor] = []
    excluded: list[ExcludedColor] = []
    contributing: list[UUID] = []
    method: str | None = None
    version: str | None = None
    seen: set[str] = set()
    for measurement in attempted:
        if measurement.status is not MeasurementStatus.MEASURED or measurement.palette is None:
            continue
        added = False
        for color in measurement.palette.colors:
            if color.hex.lower() in seen or len(palette) >= MAX_PALETTE:
                continue
            seen.add(color.hex.lower())
            palette.append(
                PaletteColor(
                    value=color.hex,
                    # Measured dominance is not a design role; a second logo's
                    # colors can only ever be supporting.
                    role="supporting" if palette else color.role,
                    source=PaletteSource.ASSET_EXTRACTION,
                    source_asset_id=measurement.asset_id,
                    foreground_share=color.foreground_share,
                    luminance=color.luminance,
                    tone=color.tone,
                    saturation_band=color.saturation_band,
                )
            )
            added = True
        if added:
            contributing.append(measurement.asset_id)
            method = method or measurement.palette.method
            version = version or measurement.palette.version
            excluded.extend(measurement.palette.excluded)

    if palette:
        return palette, PaletteStatus.MEASURED, {
            "palette_method": method,
            "analysis_version": version,
            "measured_asset_ids": contributing,
            "excluded_colors": excluded[:6],
        }
    failures = [m.failure_code for m in attempted if m.status is MeasurementStatus.FAILED and m.failure_code]
    if failures:
        return [], PaletteStatus.FAILED, {"analysis_failure": failures[0]}
    return [], PaletteStatus.UNAVAILABLE, {}


def build_brand_visual_profile(brief: CreativeBrief, assets: Sequence[CreativeBriefAsset]) -> BrandVisualProfile:
    """Deterministic and side-effect free. Colors measured from the official
    logo arrive on `brief.brand_measurements` (computed by
    app.services.brand_measurement before planning); a brief without them
    simply has `palette_status == not_performed`."""
    sources: list[str] = []
    palette: list[PaletteColor] = []
    status = PaletteStatus.NOT_PERFORMED
    measured_fields: dict = {}

    if brief.brand_colors is not None:
        for role in ("primary", "secondary", "accent"):
            color = _safe_color(getattr(brief.brand_colors, role))
            if color:
                palette.append(PaletteColor(value=color, role=role, source=PaletteSource.BRAND_CONFIG))
        if palette:
            sources.append(SOURCE_BRAND_COLORS)
            status = PaletteStatus.CONFIGURED

    logos = official_logos(assets)
    if logos:
        sources.append(SOURCE_OFFICIAL_LOGO)

    if status is not PaletteStatus.CONFIGURED:
        palette, status, measured_fields = _measured_palette(brief, logos)
        if status is PaletteStatus.MEASURED:
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
        palette_status=status,
        **measured_fields,
        visual_style=visual_style,
        typography_hints=typography_hints,
        source_asset_ids=[logo.id for logo in logos],
        sources=sources,
        has_official_logo=bool(logos),
    )
