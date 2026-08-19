import type { BlockConfig } from "./blocks.ts";
import type { SEOConfig } from "./seo.ts";

export interface PageConfig {
  path: string;
  blocks: BlockConfig[];
  /** Overrides the site-wide `seo` default for this page when set. */
  seo?: SEOConfig;
}
