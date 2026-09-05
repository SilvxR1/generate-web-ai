import type { BusinessProfile, WebsiteConfig as BusinessWebsiteConfig } from "@generate-web-ai/business-config-types";
import type { SEOConfig } from "@generate-web-ai/site-config";

/** Blank/whitespace-only strings are treated as absent, not as real
 * content — an empty `""` from BusinessConfig must fall through to the
 * next source rather than short-circuiting it (`??` alone wouldn't do
 * this, since `""` is not nullish). */
function isBlank(value: string | null | undefined): value is null | undefined | "" {
  return value == null || value.trim().length === 0;
}

/** title/description always resolve to something real: explicit
 * website.seo overrides first, then the business's own description,
 * then a deterministic fallback built from name/location — never
 * invented ad copy, and never blank. */
export function buildSeo(profile: BusinessProfile, website: BusinessWebsiteConfig | undefined): SEOConfig {
  const explicitTitle = website?.seo?.title;
  const title = isBlank(explicitTitle) ? profile.name : explicitTitle;

  const explicitDescription = website?.seo?.description;
  const location = profile.location?.city;
  const description = !isBlank(explicitDescription)
    ? explicitDescription
    : !isBlank(profile.description)
      ? profile.description
      : !isBlank(location)
        ? `${profile.name} — servicios profesionales en ${location}`
        : `${profile.name} — servicios profesionales`;

  return {
    title,
    description,
    ...(website?.seo?.og_image ? { ogImage: { src: website.seo.og_image.url, alt: website.seo.og_image.alt } } : {}),
  };
}
