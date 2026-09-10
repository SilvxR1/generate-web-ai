import type { LocalBusinessConfig } from "./business.ts";
import type { BrandConfig } from "./brand.ts";
import type { FeatureConfig } from "./features.ts";
import type { PageConfig } from "./pages.ts";
import type { SEOConfig } from "./seo.ts";
import type { ThemeConfig } from "./theme.ts";
import type { WhatsAppConfig } from "./whatsapp.ts";

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
  /** WhatsApp CTA configuration (P1.1) — optional, and only ever rendered
   * (floating button / contact-section CTA) when `enabled` is true. */
  whatsapp?: WhatsAppConfig;
  /** Set server-side at build/publish time (apps/api's
   * app.publishing.drafts/service, never trusted from anywhere else) —
   * the generated static site's only way to know which business it
   * belongs to. Used by apps/site-builder's analytics beacon
   * (POST /public/businesses/{businessId}/events); every analytics call
   * is a safe no-op when this is absent (e.g. a local `astro build` run
   * outside the real publishing pipeline). */
  businessId?: string;
}
