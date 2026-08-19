// Block content types intentionally mirror the `content` prop shapes
// defined inside `packages/blocks`' `.astro` components (HeroContent,
// ServicesContent, ...) field-for-field, but are declared independently
// here rather than imported from `blocks`. Those types live inside `.astro`
// files, which only Astro's own checker can parse; importing them into this
// plain-TypeScript package would force the schema to depend on Astro
// tooling, which defeats the point of a SiteConfig being describable and
// generatable as data alone. The renderer package is what bridges the two.
import type { AssetConfig } from "./assets.ts";

/** A single call-to-action link. `variant` maps onto the `ui` Button variant. */
export interface BlockActionConfig {
  label: string;
  href: string;
  variant?: "solid" | "outline" | "ghost";
}

export interface HeroBlockContent {
  eyebrow?: string;
  heading: string;
  subheading?: string;
  primaryAction?: BlockActionConfig;
  secondaryAction?: BlockActionConfig;
  image?: AssetConfig;
}

export interface ServiceItemConfig {
  title: string;
  description: string;
  /** Ignored when `image` is set. */
  icon?: string;
  /** Takes precedence over `icon` when both are set. */
  image?: AssetConfig;
  action?: BlockActionConfig;
}

export interface ServicesBlockContent {
  heading?: string;
  subheading?: string;
  items: ServiceItemConfig[];
}

export interface ProcessStepConfig {
  title: string;
  description: string;
  icon?: string;
}

export interface ProcessBlockContent {
  heading?: string;
  subheading?: string;
  steps: ProcessStepConfig[];
}

export interface GalleryBeforeAfterConfig {
  before: AssetConfig;
  after: AssetConfig;
  /** Defaults to "Before". */
  beforeLabel?: string;
  /** Defaults to "After". */
  afterLabel?: string;
}

export interface GalleryItemConfig {
  title: string;
  category?: string;
  image: AssetConfig;
  description?: string;
  link?: BlockActionConfig;
  beforeAfter?: GalleryBeforeAfterConfig;
}

export interface GalleryBlockContent {
  heading?: string;
  subheading?: string;
  items: GalleryItemConfig[];
}

export interface FeatureItemConfig {
  title: string;
  description: string;
  icon?: string;
}

export interface FeaturesBlockContent {
  heading?: string;
  subheading?: string;
  items: FeatureItemConfig[];
}

export interface TestimonialItemConfig {
  quote: string;
  author: string;
  role?: string;
  company?: string;
  avatar?: AssetConfig;
  /** Optional 1-5 star rating. */
  rating?: number;
}

export interface TestimonialsBlockContent {
  heading?: string;
  subheading?: string;
  items: TestimonialItemConfig[];
}

export interface FAQItemConfig {
  question: string;
  answer: string;
}

export interface FAQBlockContent {
  heading?: string;
  subheading?: string;
  items: FAQItemConfig[];
}

export interface CTABlockContent {
  heading: string;
  subheading?: string;
  primaryAction: BlockActionConfig;
  secondaryAction?: BlockActionConfig;
}

export interface ContactDetailConfig {
  label: string;
  value: string;
  href?: string;
}

export interface ContactFormFieldOptionConfig {
  label: string;
  value: string;
}

interface ContactFormFieldConfigBase {
  name: string;
  label: string;
  required?: boolean;
  placeholder?: string;
}

export interface TextContactFormFieldConfig extends ContactFormFieldConfigBase {
  type?: "text" | "email" | "tel" | "textarea";
}

export interface SelectContactFormFieldConfig extends ContactFormFieldConfigBase {
  type: "select";
  options: ContactFormFieldOptionConfig[];
}

export interface RadioContactFormFieldConfig extends ContactFormFieldConfigBase {
  type: "radio";
  options: ContactFormFieldOptionConfig[];
}

/** No `options` describes a single toggle; `options` describes a checkbox group. */
export interface CheckboxContactFormFieldConfig extends ContactFormFieldConfigBase {
  type: "checkbox";
  options?: ContactFormFieldOptionConfig[];
}

/** Configuration layer only — no upload infrastructure implemented yet. */
export interface FileContactFormFieldConfig extends ContactFormFieldConfigBase {
  type: "file";
  accept?: string;
  multiple?: boolean;
}

export type ContactFormFieldConfig =
  | TextContactFormFieldConfig
  | SelectContactFormFieldConfig
  | RadioContactFormFieldConfig
  | CheckboxContactFormFieldConfig
  | FileContactFormFieldConfig;

export interface ContactFormConfig {
  action?: string;
  method?: "get" | "post";
  fields: ContactFormFieldConfig[];
  submitLabel?: string;
}

export interface ContactBlockContent {
  heading?: string;
  subheading?: string;
  details?: ContactDetailConfig[];
  form?: ContactFormConfig;
}

interface BlockConfigBase {
  /** Anchor id for in-page navigation (e.g. a nav link to "#services"). */
  id?: string;
}

export interface HeroBlockConfig extends BlockConfigBase {
  type: "hero";
  content: HeroBlockContent;
}

export interface ServicesBlockConfig extends BlockConfigBase {
  type: "services";
  content: ServicesBlockContent;
}

export interface FeaturesBlockConfig extends BlockConfigBase {
  type: "features";
  content: FeaturesBlockContent;
}

export interface ProcessBlockConfig extends BlockConfigBase {
  type: "process";
  content: ProcessBlockContent;
}

export interface GalleryBlockConfig extends BlockConfigBase {
  type: "gallery";
  content: GalleryBlockContent;
}

export interface TestimonialsBlockConfig extends BlockConfigBase {
  type: "testimonials";
  content: TestimonialsBlockContent;
}

export interface FAQBlockConfig extends BlockConfigBase {
  type: "faq";
  content: FAQBlockContent;
}

export interface CTABlockConfig extends BlockConfigBase {
  type: "cta";
  content: CTABlockContent;
}

export interface ContactBlockConfig extends BlockConfigBase {
  type: "contact";
  content: ContactBlockContent;
}

/**
 * Every block a page can be built from, discriminated on `type` so a
 * consumer — an AI, the renderer, a future editing form — can narrow to
 * the exact `content` shape for a given block without casts.
 */
export type BlockConfig =
  | HeroBlockConfig
  | ServicesBlockConfig
  | FeaturesBlockConfig
  | ProcessBlockConfig
  | GalleryBlockConfig
  | TestimonialsBlockConfig
  | FAQBlockConfig
  | CTABlockConfig
  | ContactBlockConfig;

export type BlockType = BlockConfig["type"];

/**
 * Single source of truth for which block types exist. Keep in sync with the
 * `BlockConfig` union above — add a new type here whenever a new variant is
 * added there.
 */
export const BLOCK_TYPES = [
  "hero",
  "services",
  "features",
  "process",
  "gallery",
  "testimonials",
  "faq",
  "cta",
  "contact",
] as const satisfies readonly BlockType[];

export function isKnownBlockType(value: string): value is BlockType {
  return (BLOCK_TYPES as readonly string[]).includes(value);
}

/**
 * Throws a clear, specific error for a block whose `type` isn't one the
 * renderer knows how to map to a component. `BlockConfig` guarantees this
 * statically for hand-written TypeScript, but content produced elsewhere
 * (parsed JSON, AI output) isn't guaranteed to satisfy it at runtime — this
 * is the guard that turns an unrecognized type into a clear failure instead
 * of a silently empty section.
 */
export function assertKnownBlockType(block: BlockConfig): void {
  if (!isKnownBlockType(block.type)) {
    throw new Error(
      `Unknown block type: ${JSON.stringify(block.type)}. Known types: ${BLOCK_TYPES.join(", ")}.`,
    );
  }
}
