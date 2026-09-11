/**
 * Design family resolution — LR-07's "InternalCreativeProvider must be
 * capable of meaningful website differentiation using the existing
 * deterministic design system" without Higgsfield.
 *
 * Deliberately NOT `if business_type == "amigurumi": pink template`: the
 * only inputs are (1) `BusinessProfile.industry`, a small closed
 * vocabulary already validated upstream, and (2) `BrandConfig.visual_style`,
 * a free-text creative-direction field that already exists specifically
 * for this ("warm and editorial" is that field's own doc example) — used
 * only to disambiguate the two verticals (`other`, `ecommerce`) broad
 * enough to cover almost any kind of business. A structured vertical
 * (`home_renovation`, `clinic`, ...) always wins outright, so a renovation
 * business whose `visual_style` happens to say "warm, mediterranean"
 * still reads as construction/trade, not artisan — a keyword match is
 * only ever a tiebreaker for an ambiguous bucket, never an override of a
 * known fact.
 *
 * Every family's tokens are a fixed lookup, not a random or per-business
 * computation: the same BusinessConfig always resolves to the same
 * family and the same tokens (LR-07's "no randomness as fake creativity"
 * / determinism requirement).
 */
import type { BusinessVertical } from "@generate-web-ai/business-config-types";
import type { ThemeConfig } from "@generate-web-ai/site-config";

export type DesignFamily = "artisan" | "construction" | "professional_services" | "hospitality" | "generic";

export interface DesignTokens {
  family: DesignFamily;
  /** Used only when the business has no explicit `brand.colors` of its
   * own — real brand colors always take priority (LR-05/LR-07's "real
   * assets/brand win" rule applies to color choices too). */
  colors: ThemeConfig["colors"];
  /** Same rule as `colors`: only used when the business has no explicit
   * `brand.typography`. */
  fonts: ThemeConfig["fonts"];
  /** Not part of BrandConfig at all (BusinessConfig has no field for it)
   * — always generator-decided chrome, so this applies to every
   * business, brand or no brand. */
  radius: ThemeConfig["radius"];
  /** Where a real gallery/portfolio image set is inserted in the page,
   * relative to the other optional blocks. */
  galleryPlacement: "after_hero" | "after_services" | "after_about";
  ctaVariant: "default" | "emphasis";
  /** Alternates `background: "surface"` on every other optional section
   * for a warmer, less flat page rhythm. Off for families that read
   * better as a flat, restrained surface (professional/trust-led). */
  alternateSurfaces: boolean;
}

const VERTICAL_TO_FAMILY: Partial<Record<BusinessVertical, DesignFamily>> = {
  home_renovation: "construction",
  real_estate: "construction",
  clinic: "professional_services",
  agency: "professional_services",
  b2b_services: "professional_services",
  restaurant: "hospitality",
  hotel: "hospitality",
};

// Verticals broad enough to describe almost any small business — the
// only case `visual_style` free text is allowed to decide the family.
const AMBIGUOUS_VERTICALS = new Set<BusinessVertical>(["ecommerce", "other"]);

const VISUAL_STYLE_KEYWORDS: Array<{ family: DesignFamily; pattern: RegExp }> = [
  { family: "artisan", pattern: /\b(artisan|handmade|hand-made|hecho a mano|craft|crochet|amigurumi|boutique|organic)\b/i },
  { family: "construction", pattern: /\b(structural|architectural|industrial|robust|construction|reforma)\b/i },
  { family: "hospitality", pattern: /\b(hospitality|culinary|cozy|restaurant|hotel|cuisine)\b/i },
  { family: "professional_services", pattern: /\b(corporate|professional|trust|clinical|consult)\b/i },
];

function matchVisualStyleFamily(visualStyle: string | null | undefined): DesignFamily | undefined {
  if (!visualStyle) return undefined;
  const match = VISUAL_STYLE_KEYWORDS.find(({ pattern }) => pattern.test(visualStyle));
  return match?.family;
}

/** A business with real, substantial product/gallery photography and no
 * other signal (no structured vertical family, no `visual_style` hint —
 * most likely because it has no `brand` at all yet) reads as a
 * product/portfolio-led business regardless of what it sells: "a
 * business with strong photography should receive layouts that exploit
 * photography" (LR-07). Two real photos is the deliberately low bar —
 * this only ever applies to the `other`/`ecommerce` catch-all verticals
 * that have no more specific signal to go on. */
const SUBSTANTIAL_GALLERY_THRESHOLD = 2;

export function resolveDesignFamily(
  industry: BusinessVertical,
  visualStyle: string | null | undefined,
  realGalleryAssetCount = 0,
): DesignFamily {
  if (!AMBIGUOUS_VERTICALS.has(industry)) {
    return VERTICAL_TO_FAMILY[industry] ?? "generic";
  }
  const styleFamily = matchVisualStyleFamily(visualStyle);
  if (styleFamily) return styleFamily;
  if (realGalleryAssetCount >= SUBSTANTIAL_GALLERY_THRESHOLD) return "artisan";
  return VERTICAL_TO_FAMILY[industry] ?? "generic";
}

const DESIGN_TOKENS: Record<DesignFamily, DesignTokens> = {
  artisan: {
    family: "artisan",
    colors: {
      primary: "#b5651d",
      secondary: "#6b4226",
      accent: "#e8a33d",
      background: "#fdf8f3",
      foreground: "#3a2e28",
    },
    fonts: { sans: "'Trebuchet MS', 'Segoe UI', sans-serif", display: "Georgia, 'Times New Roman', serif" },
    radius: { base: "1rem", lg: "1.5rem" },
    galleryPlacement: "after_hero",
    ctaVariant: "default",
    alternateSurfaces: true,
  },
  construction: {
    family: "construction",
    colors: {
      primary: "#1f2937",
      secondary: "#374151",
      accent: "#d97706",
      background: "#ffffff",
      foreground: "#111827",
    },
    fonts: { sans: "-apple-system, 'Segoe UI', sans-serif", display: "'Arial Black', 'Helvetica Neue', sans-serif" },
    radius: { base: "0.25rem", lg: "0.375rem" },
    galleryPlacement: "after_services",
    ctaVariant: "emphasis",
    alternateSurfaces: false,
  },
  professional_services: {
    family: "professional_services",
    colors: {
      primary: "#1e3a5f",
      secondary: "#64748b",
      accent: "#0ea5e9",
      background: "#ffffff",
      foreground: "#0f172a",
    },
    fonts: { sans: "-apple-system, 'Segoe UI', sans-serif" },
    radius: { base: "0.375rem", lg: "0.5rem" },
    galleryPlacement: "after_about",
    ctaVariant: "default",
    alternateSurfaces: false,
  },
  hospitality: {
    family: "hospitality",
    colors: {
      primary: "#7c2d12",
      secondary: "#78350f",
      accent: "#ea580c",
      background: "#fffbf5",
      foreground: "#292524",
    },
    fonts: { sans: "Georgia, 'Times New Roman', serif", display: "Georgia, 'Times New Roman', serif" },
    radius: { base: "0.75rem", lg: "1rem" },
    galleryPlacement: "after_hero",
    ctaVariant: "default",
    alternateSurfaces: true,
  },
  generic: {
    family: "generic",
    colors: {
      primary: "#2563eb",
      secondary: "#0f766e",
      accent: "#f59e0b",
      background: "#ffffff",
      foreground: "#111827",
    },
    fonts: { sans: "Inter, system-ui, sans-serif" },
    radius: { base: "0.5rem", lg: "0.75rem" },
    galleryPlacement: "after_about",
    ctaVariant: "default",
    alternateSurfaces: false,
  },
};

export function getDesignTokens(family: DesignFamily): DesignTokens {
  return DESIGN_TOKENS[family];
}
