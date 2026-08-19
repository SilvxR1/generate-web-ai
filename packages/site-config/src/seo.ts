import type { AssetConfig } from "./assets.ts";

/**
 * Basic per-page/site SEO metadata. Deliberately minimal: title, description,
 * and an optional social preview image. No structured data (schema.org),
 * canonical URL handling, or sitemap generation yet — those are a later,
 * explicit decision, not implied by this shape.
 */
export interface SEOConfig {
  title: string;
  description: string;
  ogImage?: AssetConfig;
}
