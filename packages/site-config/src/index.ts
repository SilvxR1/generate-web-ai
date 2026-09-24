// Entry point for the site configuration schema package. A client site is
// described as data — SiteConfig -> brand, theme, pages, blocks, features —
// which @generate-web-ai/renderer turns into Astro components. This package
// has no Astro dependency: it's the layer an AI (or a human) generates.
export type { AssetConfig, LocalImageRef } from "./assets.ts";
export type { BrandConfig } from "./brand.ts";
export type { LocalBusinessAddress, LocalBusinessOpeningHours, LocalBusinessConfig, LocalBusinessJsonLd } from "./business.ts";
export { buildLocalBusinessJsonLd } from "./business.ts";
export type { ThemeColorConfig, ThemeFontConfig, ThemeRadiusConfig, ThemeSpacingConfig, ThemeConfig } from "./theme.ts";
export type { FeatureConfig } from "./features.ts";
export type { BookingServiceConfig, BookingDayConfig, BookingSlotConfig, BookingReservationInput } from "./booking.ts";
export type {
  BlockActionConfig,
  HeroStatConfig,
  HeroBlockContent,
  HeroBlockConfig,
  ServiceItemConfig,
  ServicesBlockContent,
  ServicesBlockConfig,
  FeatureItemConfig,
  FeaturesBlockContent,
  FeaturesBlockConfig,
  ProcessStepConfig,
  ProcessBlockContent,
  ProcessBlockConfig,
  GalleryBeforeAfterConfig,
  GalleryItemConfig,
  GalleryBlockContent,
  GalleryBlockConfig,
  TestimonialItemConfig,
  TestimonialsBlockContent,
  TestimonialsBlockConfig,
  FAQItemConfig,
  FAQBlockContent,
  FAQBlockConfig,
  CTABlockContent,
  CTABlockConfig,
  ContactDetailConfig,
  ContactFormFieldOptionConfig,
  TextContactFormFieldConfig,
  SelectContactFormFieldConfig,
  RadioContactFormFieldConfig,
  CheckboxContactFormFieldConfig,
  FileContactFormFieldConfig,
  ContactFormFieldConfig,
  ContactFormConfig,
  ContactWhatsAppCtaConfig,
  ContactBlockContent,
  ContactBlockConfig,
  LegalSectionConfig,
  LegalTextBlockContent,
  LegalTextBlockConfig,
  BlockConfig,
  BlockType,
} from "./blocks.ts";
export { BLOCK_TYPES, isKnownBlockType, assertKnownBlockType } from "./blocks.ts";
export type { PageConfig } from "./pages.ts";
export type { SEOConfig } from "./seo.ts";
export type { SiteConfig, SiteNavigationItem } from "./site-config.ts";
export type { WhatsAppConfig } from "./whatsapp.ts";
export { exampleSiteConfig } from "./example.ts";
export type {
  CreativeStrategy,
  CtaVariant,
  DensityScale,
  GalleryLayout,
  HeroLayout,
  MovableSection,
  PaletteDerivation,
  PaletteDirection,
  PaletteMode,
  RadiusScale,
  SurfaceMode,
  TypographyPairing,
  WebsiteCreativeDirection,
  WebsiteCreativeDirectionValidation,
  WebsiteDesignFamily,
} from "./creative-direction.ts";
export {
  CREATIVE_STRATEGIES,
  CTA_VARIANTS,
  DENSITY_SCALES,
  GALLERY_LAYOUTS,
  GALLERY_MAX_ITEMS_MAX,
  GALLERY_MAX_ITEMS_MIN,
  HERO_LAYOUTS,
  MOVABLE_SECTIONS,
  PALETTE_DERIVATIONS,
  PALETTE_MODES,
  RADIUS_SCALES,
  RATIONALE_MAX_LENGTH,
  SURFACE_MODES,
  TYPOGRAPHY_PAIRINGS,
  WEBSITE_CREATIVE_DIRECTION_VERSION,
  WEBSITE_DESIGN_FAMILIES,
  validateWebsiteCreativeDirection,
} from "./creative-direction.ts";
