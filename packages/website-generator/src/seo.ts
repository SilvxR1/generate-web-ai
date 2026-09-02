import type { BusinessProfile, WebsiteConfig as BusinessWebsiteConfig } from "@generate-web-ai/business-config-types";
import type { SEOConfig } from "@generate-web-ai/site-config";
import type { WebsiteGeneratorPreset } from "./presets.ts";

/** title/description always resolve to something real: explicit
 * website.seo overrides first, then the business's own name/description,
 * never invented ad copy. */
export function buildSeo(
  profile: BusinessProfile,
  website: BusinessWebsiteConfig | undefined,
  preset: WebsiteGeneratorPreset,
): SEOConfig {
  const title = website?.seo?.title ?? profile.name;
  const description =
    website?.seo?.description ?? profile.description ?? preset.heroSubheadingFallback ?? profile.name;

  return {
    title,
    description,
    ...(website?.seo?.og_image ? { ogImage: { src: website.seo.og_image.url, alt: website.seo.og_image.alt } } : {}),
  };
}
