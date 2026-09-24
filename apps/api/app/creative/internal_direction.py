"""derive_website_creative_direction (A8.2.2) — how the BASIC/internal
creative provider turns a CreativeBrief into a canonical
WebsiteCreativeDirection v1 (app.domain.creative.website_direction):
a pure, deterministic function. No randomness, no network, no AI, no
provider call.

It reads only a small PRESENTATION projection of the brief
(DirectionContext): the requested brand strategy, the industry, the
brand's own visual_style keywords, whether brand colours exist, and how
many real gallery-worthy photos and hero-capable images are on file. It
never reads the business name, description, services, contact details,
location or reviews, so no business fact can end up in a direction.

Same DirectionContext + same strategy -> the same direction, always.
Nothing here is seeded by generation id or time: repeating a request for
an unchanged business yields an identical direction. Offering a second,
different new direction later needs an explicit variant input, not
hidden variation.

Family mapping (mirrors packages/website-generator/src/design.ts'
resolveDesignFamily; both are held to
packages/website-generator/fixtures/design-family.conformance.json):
- Unambiguous verticals map directly: home_renovation and real_estate →
  construction; clinic, agency, b2b_services → professional_services;
  restaurant, hotel → hospitality.
- ecommerce/other: first a visual_style keyword match, then a real
  gallery of at least 2 photos → artisan, otherwise generic.
- Anything unknown → generic.

Not wired into generateSiteConfig yet (A8.2.3) and not persisted or
exposed (A8.2.4): the direction exists only on the in-memory
CreativeGenerationResult.
"""

import re
from dataclasses import dataclass

from app.domain.creative import CreativeBrief
from app.domain.creative.website_direction import (
    WebsiteCreativeDirection,
)
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, BrandStrategy

# --- Design-family resolution (mirror of design.ts) -----------------------

_VERTICAL_TO_FAMILY: dict[str, str] = {
    "home_renovation": "construction",
    "real_estate": "construction",
    "clinic": "professional_services",
    "agency": "professional_services",
    "b2b_services": "professional_services",
    "restaurant": "hospitality",
    "hotel": "hospitality",
}
_AMBIGUOUS_VERTICALS = frozenset({"ecommerce", "other"})
_VISUAL_STYLE_KEYWORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "artisan",
        re.compile(r"\b(artisan|handmade|hand-made|hecho a mano|craft|crochet|amigurumi|boutique|organic)\b", re.I),
    ),
    ("construction", re.compile(r"\b(structural|architectural|industrial|robust|construction|reforma)\b", re.I)),
    ("hospitality", re.compile(r"\b(hospitality|culinary|cozy|restaurant|hotel|cuisine)\b", re.I)),
    ("professional_services", re.compile(r"\b(corporate|professional|trust|clinical|consult)\b", re.I)),
)
_SUBSTANTIAL_GALLERY_THRESHOLD = 2

# Mirrors assets.ts' GALLERY_CATEGORIES / usable() for counting purposes.
_GALLERY_CATEGORIES = frozenset(
    {
        AssetCategory.GALLERY,
        AssetCategory.PROJECT,
        AssetCategory.PRODUCT,
        AssetCategory.BEFORE,
        AssetCategory.AFTER,
        AssetCategory.TEAM,
        AssetCategory.FACILITY,
    }
)


def resolve_design_family(industry: str, visual_style: str | None, real_gallery_asset_count: int = 0) -> str:
    if industry not in _AMBIGUOUS_VERTICALS:
        return _VERTICAL_TO_FAMILY.get(industry, "generic")
    if visual_style:
        for family, pattern in _VISUAL_STYLE_KEYWORDS:
            if pattern.search(visual_style):
                return family
    if real_gallery_asset_count >= _SUBSTANTIAL_GALLERY_THRESHOLD:
        return "artisan"
    return _VERTICAL_TO_FAMILY.get(industry, "generic")


# --- Presentation projection of the brief ---------------------------------


@dataclass(frozen=True)
class DirectionContext:
    """Everything the derivation is allowed to see, and nothing else."""

    strategy: BrandStrategy
    industry: str
    visual_style: str | None
    has_brand_colors: bool
    real_gallery_asset_count: int
    has_hero_image: bool


def direction_context_from_brief(brief: CreativeBrief) -> DirectionContext:
    usable_images = [
        asset
        for asset in brief.available_assets
        if asset.kind is AssetKind.IMAGE and asset.category is not AssetCategory.LOW_QUALITY and asset.url.strip()
    ]
    gallery_images = [asset for asset in usable_images if asset.category in _GALLERY_CATEGORIES]
    # resolveDesignFamily's count only includes real photos (generated ones
    # never make an image-rich business look artisan).
    real_gallery = [asset for asset in gallery_images if asset.origin is not AssetOrigin.GENERATED]
    has_hero_image = any(
        asset.category is AssetCategory.HERO_CANDIDATE or asset.category in _GALLERY_CATEGORIES
        for asset in usable_images
    )
    return DirectionContext(
        strategy=brief.brand_strategy,
        industry=brief.industry,
        visual_style=brief.visual_style,
        has_brand_colors=brief.brand_colors is not None,
        real_gallery_asset_count=len(real_gallery),
        has_hero_image=has_hero_image,
    )


# --- Family presentation profiles (today's design.ts token choices) ------


@dataclass(frozen=True)
class _FamilyProfile:
    pairing: str
    radius: str
    section_order: tuple[str, str, str]
    surfaces: str
    cta: str
    label: str  # plain-language rationale wording


# Each profile restates what design.ts already renders for that family:
# its font stack (as a canonical pairing), its radius band, its gallery
# placement (as a section order), its surfaces and its CTA variant.
_FAMILY_PROFILES: dict[str, _FamilyProfile] = {
    "artisan": _FamilyProfile(
        "humanist_serif_display", "round", ("gallery", "services", "about"), "alternate", "default", "warm, crafted"
    ),
    "construction": _FamilyProfile(
        "bold_display_sans", "sharp", ("services", "gallery", "about"), "flat", "emphasis", "solid, structured"
    ),
    "professional_services": _FamilyProfile(
        "system_sans", "soft", ("services", "about", "gallery"), "flat", "default", "clear, professional"
    ),
    "hospitality": _FamilyProfile(
        "classic_serif", "soft", ("gallery", "services", "about"), "alternate", "default", "classic, editorial"
    ),
    "generic": _FamilyProfile(
        "modern_sans", "soft", ("services", "about", "gallery"), "flat", "default", "clean, modern"
    ),
}

# NEW_DIRECTION's alternative family: a deliberately different but
# still-compatible presentation for the same kind of business (a crafted
# brand stays warm; a structured brand stays structured).
_NEW_DIRECTION_FAMILY: dict[str, str] = {
    "artisan": "hospitality",
    "hospitality": "artisan",
    "construction": "professional_services",
    "professional_services": "generic",
    "generic": "professional_services",
}

_PAIRING_LABELS: dict[str, str] = {
    "modern_sans": "modern sans-serif",
    "system_sans": "clean system",
    "humanist_serif_display": "humanist type with serif headings",
    "bold_display_sans": "bold display",
    "classic_serif": "classic serif",
}

# Gallery caps (home page only; the rest of the real photos stay on file):
# PRESERVE keeps a generous but bounded gallery, EVOLVE curates it,
# NEW_DIRECTION leads with a small, deliberate selection. None approaches
# the contract's 24 ceiling — a home page is not an archive.
_GALLERY_MAX_ITEMS: dict[BrandStrategy, int] = {
    BrandStrategy.PRESERVE: 12,
    BrandStrategy.EVOLVE: 9,
    BrandStrategy.NEW_DIRECTION: 6,
}


def _has_gallery(context: DirectionContext) -> bool:
    # Rationale wording only: never describe a gallery the business
    # doesn't have. The cap itself is always set (the contract requires
    # it; the generator applies it only when real photos exist).
    return context.real_gallery_asset_count > 0


def _preserve(context: DirectionContext, family: str) -> WebsiteCreativeDirection:
    profile = _FAMILY_PROFILES[family]
    max_items = _GALLERY_MAX_ITEMS[BrandStrategy.PRESERVE]
    return WebsiteCreativeDirection.model_validate(
        {
            "version": "1",
            "strategy": BrandStrategy.PRESERVE.value,
            "family": family,
            "palette": {"mode": "brand"},
            "typography": {"pairing": profile.pairing},
            "radius": profile.radius,
            "density": "comfortable",
            "sectionOrder": list(profile.section_order),
            "hero": {"layout": "split" if context.has_hero_image else "centered"},
            "gallery": {"maxItems": max_items, "layout": "grid"},
            "surfaces": {"mode": profile.surfaces},
            "cta": {"variant": profile.cta},
            "rationale": (
                f"Keeps the current {'brand ' if context.has_brand_colors else ''}palette and {profile.label} "
                f"layout with the same section order"
                + (f", and limits the home-page gallery to {max_items} photos." if _has_gallery(context) else ".")
            ),
        }
    )


def _evolve(context: DirectionContext, family: str) -> WebsiteCreativeDirection:
    profile = _FAMILY_PROFILES[family]
    max_items = _GALLERY_MAX_ITEMS[BrandStrategy.EVOLVE]
    if context.has_brand_colors:
        palette = {"mode": "brand_derived", "derivation": "tonal_shift"}
        palette_words = "a lighter tonal range of the brand colours"
    else:
        palette = {"mode": "family"}
        palette_words = "its own palette"
    return WebsiteCreativeDirection.model_validate(
        {
            "version": "1",
            "strategy": BrandStrategy.EVOLVE.value,
            "family": family,
            "palette": palette,
            "typography": {"pairing": profile.pairing},
            "radius": profile.radius,
            "density": "airy",
            "sectionOrder": list(profile.section_order),
            "hero": {"layout": "split" if context.has_hero_image else "centered"},
            "gallery": {"maxItems": max_items, "layout": "featured_grid"},
            "surfaces": {"mode": profile.surfaces},
            "cta": {"variant": profile.cta},
            "rationale": (
                f"Keeps the recognizable {profile.label} identity with {palette_words} and more breathing room"
                + (
                    f", plus a curated gallery of {max_items} photos led by a featured image."
                    if _has_gallery(context)
                    else "."
                )
            ),
        }
    )


def _new_direction(context: DirectionContext, current_family: str) -> WebsiteCreativeDirection:
    family = _NEW_DIRECTION_FAMILY[current_family]
    profile = _FAMILY_PROFILES[family]
    max_items = _GALLERY_MAX_ITEMS[BrandStrategy.NEW_DIRECTION]
    if context.has_brand_colors:
        palette = {"mode": "brand_derived", "derivation": "contrast_up"}
        palette_words = "higher-contrast brand colours"
    else:
        palette = {"mode": "family"}
        palette_words = "a new palette"
    # Story-first order: the about section leads; an image-rich business
    # shows its photos next, otherwise its services.
    image_led = context.real_gallery_asset_count >= _SUBSTANTIAL_GALLERY_THRESHOLD
    section_order = ["about", "gallery", "services"] if image_led else ["about", "services", "gallery"]
    return WebsiteCreativeDirection.model_validate(
        {
            "version": "1",
            "strategy": BrandStrategy.NEW_DIRECTION.value,
            "family": family,
            "palette": palette,
            "typography": {"pairing": profile.pairing},
            "radius": profile.radius,
            "density": "compact",
            "sectionOrder": section_order,
            "hero": {"layout": "centered"},
            "gallery": {"maxItems": max_items, "layout": "grid"},
            "surfaces": {"mode": "flat" if profile.surfaces == "alternate" else "alternate"},
            "cta": {"variant": "emphasis"},
            "rationale": (
                f"A distinctly different {profile.label} presentation: {_PAIRING_LABELS[profile.pairing]} "
                f"typography, {palette_words}, a story-first section order, a centered hero"
                + (f", a tighter selection of {max_items} photos" if _has_gallery(context) else "")
                + " and a stronger call to action."
            ),
        }
    )


def derive_website_creative_direction(context: DirectionContext) -> WebsiteCreativeDirection:
    """The one entry point: validated through the canonical
    WebsiteCreativeDirection model on the way out (model_validate), so an
    internal direction that ever broke the contract would fail loudly
    here rather than reach a consumer."""
    current_family = resolve_design_family(context.industry, context.visual_style, context.real_gallery_asset_count)
    if context.strategy is BrandStrategy.PRESERVE:
        return _preserve(context, current_family)
    if context.strategy is BrandStrategy.EVOLVE:
        return _evolve(context, current_family)
    return _new_direction(context, current_family)
