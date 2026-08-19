import type { BrandConfig } from "./brand.ts";
import type { FeatureConfig } from "./features.ts";
import type { PageConfig } from "./pages.ts";
import type { SEOConfig } from "./seo.ts";
import type { ThemeConfig } from "./theme.ts";

export interface SiteConfig {
  brand: BrandConfig;
  theme: ThemeConfig;
  pages: PageConfig[];
  features: FeatureConfig;
  /** Site-wide default SEO metadata, used as the fallback for pages without their own `seo`. */
  seo: SEOConfig;
}
