import type { BrandConfig } from "./brand.ts";
import type { FeatureConfig } from "./features.ts";
import type { PageConfig } from "./pages.ts";
import type { ThemeConfig } from "./theme.ts";

export interface SiteConfig {
  brand: BrandConfig;
  theme: ThemeConfig;
  pages: PageConfig[];
  features: FeatureConfig;
}
