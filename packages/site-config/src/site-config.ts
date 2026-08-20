import type { LocalBusinessConfig } from "./business.ts";
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
  /** Structured business/contact data (phone, address, hours...), used to
   * generate schema.org `LocalBusiness` JSON-LD via `buildLocalBusinessJsonLd`.
   * Optional — a site with no `business` data simply doesn't emit that markup. */
  business?: LocalBusinessConfig;
}
