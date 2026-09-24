"""WebsiteCreativeDirection (A8.2.1) — the explicit Pydantic mirror of the
canonical TypeScript contract in packages/site-config
(src/creative-direction.ts): a normalized, provider-independent set of
PRESENTATION decisions a creative provider's output is reduced to before
packages/website-generator ever sees it.

Distinct from app.domain.creative.direction.CreativeDirection (P2), which
is free-form prose ("mood", "palette_direction", ...) written for the
generative frontend engine's prompts: nothing there can be applied
deterministically, while every field here is a closed enum, a bounded
integer, or a fixed section permutation that website-generator can map to
known tokens.

Presentation only, by construction — `extra="forbid"` everywhere and no
field that could carry a business fact, an asset URL/id, a font name, a
colour value, CSS/HTML, or provider metadata (model, credits, cost,
request ids belong on CreativeGeneration, never here). `rationale` is the
one free-text field: a short plain-text audit note for the owner/
operator, never rendered into the generated site.

Both implementations are held to the same
packages/site-config/fixtures/creative-direction.conformance.json
(vocabulary + valid/invalid cases), so neither can drift silently.

Versioned: only `version="1"` is accepted. A future incompatible
vocabulary becomes a separate model in a union discriminated on
`version`, so a CreativeGeneration persisted under "1" is always read
with "1" semantics.

Not wired into any runtime path yet (A8.2.1 is contract-only): the
internal provider emitting it, the generator consuming it and its
persistence are A8.2.2-A8.2.4.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator, model_validator

from app.domain.enums import BrandStrategy

WEBSITE_CREATIVE_DIRECTION_VERSION = "1"

WebsiteDesignFamily = Literal["artisan", "construction", "professional_services", "hospitality", "generic"]
PaletteDerivation = Literal["tonal_shift", "contrast_up", "muted", "vivid"]
TypographyPairing = Literal[
    "modern_sans", "system_sans", "humanist_serif_display", "bold_display_sans", "classic_serif"
]
RadiusScale = Literal["sharp", "soft", "round"]
DensityScale = Literal["compact", "comfortable", "airy"]
MovableSection = Literal["services", "gallery", "about"]
HeroLayout = Literal["split", "centered"]
GalleryLayout = Literal["grid", "featured_grid"]
SurfaceMode = Literal["alternate", "flat"]
CtaVariant = Literal["default", "emphasis"]

MOVABLE_SECTIONS: tuple[str, ...] = ("services", "gallery", "about")
GALLERY_MAX_ITEMS_MIN = 3
GALLERY_MAX_ITEMS_MAX = 24
RATIONALE_MAX_LENGTH = 280

# Plain single-line text: no markup brackets, no C0 control characters /
# DEL (non-blank is checked separately — pydantic-core's regex engine has
# no look-ahead).
_RATIONALE_PATTERN = r"^[^<>\x00-\x1f\x7f]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BrandPalette(_Strict):
    mode: Literal["brand"]


class BrandDerivedPalette(_Strict):
    mode: Literal["brand_derived"]
    derivation: PaletteDerivation


class FamilyPalette(_Strict):
    mode: Literal["family"]


PaletteDirection = Annotated[BrandPalette | BrandDerivedPalette | FamilyPalette, Field(discriminator="mode")]


class TypographyDirection(_Strict):
    pairing: TypographyPairing


class HeroDirection(_Strict):
    layout: HeroLayout


class GalleryDirection(_Strict):
    maxItems: Annotated[StrictInt, Field(ge=GALLERY_MAX_ITEMS_MIN, le=GALLERY_MAX_ITEMS_MAX)]  # noqa: N815 — mirrors the TS field name verbatim
    layout: GalleryLayout


class SurfacesDirection(_Strict):
    mode: SurfaceMode


class CtaDirection(_Strict):
    variant: CtaVariant


class WebsiteCreativeDirection(_Strict):
    version: Literal["1"]
    strategy: BrandStrategy
    family: WebsiteDesignFamily
    palette: PaletteDirection
    typography: TypographyDirection
    radius: RadiusScale
    density: DensityScale
    # A full permutation of MOVABLE_SECTIONS — never a subset, so a
    # direction can reorder real content but can never hide it; hero stays
    # first and cta/contact last, outside the direction's control.
    sectionOrder: list[MovableSection]  # noqa: N815 — mirrors the TS field name verbatim
    hero: HeroDirection
    gallery: GalleryDirection
    surfaces: SurfacesDirection
    cta: CtaDirection
    rationale: Annotated[str, StringConstraints(max_length=RATIONALE_MAX_LENGTH, pattern=_RATIONALE_PATTERN)]

    @field_validator("strategy", mode="before")
    @classmethod
    def _strategy_must_be_a_string(cls, value: object) -> object:
        # BrandStrategy is a StrEnum; only its exact string values are part
        # of the JSON contract.
        if not isinstance(value, str):
            raise ValueError("strategy must be a string")
        return value

    @field_validator("rationale")
    @classmethod
    def _rationale_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rationale must be a non-empty string")
        return value

    @field_validator("sectionOrder")
    @classmethod
    def _section_order_is_a_permutation(cls, value: list[str]) -> list[str]:
        if sorted(value) != sorted(MOVABLE_SECTIONS):
            raise ValueError(f"sectionOrder must list each of {', '.join(MOVABLE_SECTIONS)} exactly once")
        return value

    @model_validator(mode="after")
    def _preserve_keeps_the_brand_palette(self) -> "WebsiteCreativeDirection":
        if self.strategy is BrandStrategy.PRESERVE and self.palette.mode != "brand":
            raise ValueError('a "preserve" direction must keep the brand palette (palette.mode="brand")')
        return self


class UnsupportedWebsiteDirectionVersionError(ValueError):
    """A stored/received direction declares a version this code has no
    model for — never silently read as v1."""


def parse_website_direction(data: object) -> WebsiteCreativeDirection:
    """The one version-dispatch point for reading a direction back
    (persisted row, API boundary). Only v1 exists; a future version adds
    its own model and branch here instead of reinterpreting old rows."""
    if isinstance(data, WebsiteCreativeDirection):
        data = data.model_dump(mode="json")
    if not isinstance(data, dict):
        raise ValueError("A website direction must be a JSON object.")
    version = data.get("version")
    if version != WEBSITE_CREATIVE_DIRECTION_VERSION:
        raise UnsupportedWebsiteDirectionVersionError(f"Unsupported website direction version: {version!r}.")
    return WebsiteCreativeDirection.model_validate(data)
