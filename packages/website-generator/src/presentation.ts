/**
 * resolvePresentation (A8.2.3) is the one place a WebsiteCreativeDirection
 * becomes concrete presentation decisions. The block builders never branch
 * on the direction themselves; they receive a resolved result.
 *
 * With no direction it reproduces generateSiteConfig's previous behaviour
 * exactly: the family from resolveDesignFamily, the brand theme (or the
 * family's), the family's gallery placement, surfaces and CTA variant, an
 * unlimited gallery and no layout variants.
 *
 * With a direction, presentation comes from it:
 * - theme family (palette fallback) → direction.family
 * - colours → direction.palette (see resolveColors)
 * - fonts → direction.typography.pairing. Exception: a "preserve"
 *   direction keeps the business's own configured brand typography.
 * - radius → direction.radius
 * - section spacing → direction.density ("comfortable" = today's)
 * - order of the optional sections, hero and gallery layout, gallery cap,
 *   surfaces, CTA variant → the matching direction fields.
 *
 * Content never changes. The copy preset (section headings, CTA wording)
 * always follows the business's own content family, never
 * direction.family, so a new direction can't put another industry's
 * wording on the page. `rationale` is never read here.
 */
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type {
  GalleryLayout,
  HeroLayout,
  MovableSection,
  RadiusScale,
  ThemeConfig,
  ThemeSpacingConfig,
  TypographyPairing,
  WebsiteCreativeDirection,
  WebsiteDesignFamily,
} from "@generate-web-ai/site-config";
import { getDesignTokens, resolveDesignFamily, type DesignTokens } from "./design.ts";
import { deriveBrandPalette } from "./palette.ts";

export interface ResolvedPresentation {
  /** The business's own content family — drives the copy preset only. */
  contentFamily: WebsiteDesignFamily;
  theme: ThemeConfig;
  /** Order of the optional sections between the hero and cta/contact. */
  sectionOrder: MovableSection[];
  heroLayout?: HeroLayout;
  gallery: { maxItems?: number; layout?: GalleryLayout };
  alternateSurfaces: boolean;
  ctaVariant: "default" | "emphasis";
}

const PLACEMENT_ORDER: Record<DesignTokens["galleryPlacement"], MovableSection[]> = {
  after_hero: ["gallery", "services", "about"],
  after_services: ["services", "gallery", "about"],
  after_about: ["services", "about", "gallery"],
};

/** The same safe, local font stacks the design families already ship. */
export const TYPOGRAPHY_STACKS: Record<TypographyPairing, ThemeConfig["fonts"]> = {
  modern_sans: { sans: "Inter, system-ui, sans-serif" },
  system_sans: { sans: "-apple-system, 'Segoe UI', sans-serif" },
  humanist_serif_display: { sans: "'Trebuchet MS', 'Segoe UI', sans-serif", display: "Georgia, 'Times New Roman', serif" },
  bold_display_sans: { sans: "-apple-system, 'Segoe UI', sans-serif", display: "'Arial Black', 'Helvetica Neue', sans-serif" },
  classic_serif: { sans: "Georgia, 'Times New Roman', serif", display: "Georgia, 'Times New Roman', serif" },
};

export const RADIUS_TOKENS: Record<RadiusScale, ThemeConfig["radius"]> = {
  sharp: { base: "0.25rem", lg: "0.375rem" },
  soft: { base: "0.5rem", lg: "0.75rem" },
  round: { base: "1rem", lg: "1.5rem" },
};

/** "comfortable" is deliberately absent: it means no override, so each
 * block keeps its built-in spacing (today's rhythm). */
export const DENSITY_SPACING: Record<"compact" | "airy", ThemeSpacingConfig> = {
  compact: {
    sectionSm: "clamp(2rem, 1.8rem + 1vw, 2.75rem)",
    sectionMd: "clamp(2.5rem, 2.2rem + 1.5vw, 3.5rem)",
    sectionLg: "clamp(3rem, 2.5rem + 2vw, 4.25rem)",
  },
  airy: {
    sectionSm: "clamp(4rem, 3.5rem + 2vw, 5.5rem)",
    sectionMd: "clamp(4.5rem, 4rem + 3vw, 7rem)",
    sectionLg: "clamp(5rem, 4.5rem + 4vw, 8.5rem)",
  },
};

function baselineTheme(config: BusinessConfig, tokens: DesignTokens): ThemeConfig {
  const { brand } = config;
  // Pydantic serializes an omitted `display` as null; ThemeFontConfig
  // expects undefined, so it's normalized here.
  return brand
    ? {
        colors: brand.colors,
        fonts: { sans: brand.typography.sans, display: brand.typography.display ?? undefined },
        radius: tokens.radius,
      }
    : { colors: tokens.colors, fonts: tokens.fonts, radius: tokens.radius };
}

function resolveColors(config: BusinessConfig, direction: WebsiteCreativeDirection): ThemeConfig["colors"] {
  const familyColors = getDesignTokens(direction.family).colors;
  const brandColors = config.brand?.colors;
  switch (direction.palette.mode) {
    case "family":
      return familyColors;
    case "brand":
      return brandColors ?? familyColors;
    case "brand_derived":
      if (!brandColors) return familyColors;
      // A non-hex brand colour can't be derived safely; keep the brand's own colours.
      return deriveBrandPalette(brandColors, direction.palette.derivation) ?? brandColors;
  }
}

function resolveFonts(config: BusinessConfig, direction: WebsiteCreativeDirection): ThemeConfig["fonts"] {
  const typography = config.brand?.typography;
  if (direction.strategy === "preserve" && typography) {
    return { sans: typography.sans, display: typography.display ?? undefined };
  }
  return TYPOGRAPHY_STACKS[direction.typography.pairing];
}

export function resolvePresentation(
  config: BusinessConfig,
  realGalleryAssetCount: number,
  direction?: WebsiteCreativeDirection,
): ResolvedPresentation {
  const profile = config.business_profile;
  const contentFamily = resolveDesignFamily(profile.industry, config.brand?.visual_style, realGalleryAssetCount);

  if (!direction) {
    const tokens = getDesignTokens(contentFamily);
    return {
      contentFamily,
      theme: baselineTheme(config, tokens),
      sectionOrder: PLACEMENT_ORDER[tokens.galleryPlacement],
      gallery: {},
      alternateSurfaces: tokens.alternateSurfaces,
      ctaVariant: tokens.ctaVariant,
    };
  }

  const spacing = direction.density === "comfortable" ? undefined : DENSITY_SPACING[direction.density];
  return {
    contentFamily,
    theme: {
      colors: resolveColors(config, direction),
      fonts: resolveFonts(config, direction),
      radius: RADIUS_TOKENS[direction.radius],
      ...(spacing ? { spacing } : {}),
    },
    sectionOrder: [...direction.sectionOrder],
    heroLayout: direction.hero.layout,
    gallery: { maxItems: direction.gallery.maxItems, layout: direction.gallery.layout },
    alternateSurfaces: direction.surfaces.mode === "alternate",
    ctaVariant: direction.cta.variant,
  };
}
