// Entry point for the site configuration schema package. A client site is
// described as data — SiteConfig -> brand, theme, pages, blocks, features —
// which @generate-web-ai/renderer turns into Astro components. This package
// has no Astro dependency: it's the layer an AI (or a human) generates.
export type { AssetConfig, LocalImageRef } from "./assets.ts";
export type { BrandConfig } from "./brand.ts";
export type { LocalBusinessAddress, LocalBusinessOpeningHours, LocalBusinessConfig, LocalBusinessJsonLd } from "./business.ts";
export { buildLocalBusinessJsonLd } from "./business.ts";
export type { ThemeColorConfig, ThemeFontConfig, ThemeRadiusConfig, ThemeConfig } from "./theme.ts";
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
  ContactBlockContent,
  ContactBlockConfig,
  BlockConfig,
  BlockType,
} from "./blocks.ts";
export { BLOCK_TYPES, isKnownBlockType, assertKnownBlockType } from "./blocks.ts";
export type { PageConfig } from "./pages.ts";
export type { SEOConfig } from "./seo.ts";
export type { SiteConfig } from "./site-config.ts";
export { exampleSiteConfig } from "./example.ts";
