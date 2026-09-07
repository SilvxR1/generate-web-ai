import type { BusinessProfile, WebsiteConfig as BusinessWebsiteConfig } from "@generate-web-ai/business-config-types";
import type { SEOConfig } from "@generate-web-ai/site-config";

/** Blank/whitespace-only strings are treated as absent, not as real
 * content — an empty `""` from BusinessConfig must fall through to the
 * next source rather than short-circuiting it (`??` alone wouldn't do
 * this, since `""` is not nullish). */
function isBlank(value: string | null | undefined): value is null | undefined | "" {
  return value == null || value.trim().length === 0;
}

/** The backend's SEO description max_length — see apps/api's
 * app.domain.business_config.website.SEOPreferences.description and
 * app.schemas.site_config.SiteSEOPayload.description, both 500. */
const SEO_DESCRIPTION_MAX_LENGTH = 500;

/** BusinessProfile.description (apps/api's
 * app.domain.business_config.business_profile.BusinessProfile) allows
 * up to 2000 chars — wider than a <meta description> the backend will
 * actually accept. Falling through to it verbatim used to fail
 * publish with a 422 for any business whose real description ran past
 * 500 chars; this closes that gap by trimming to a word boundary
 * (never invents new content, never cuts mid-word) and marking the cut
 * with an ellipsis — a no-op for anything already within the limit. */
function truncateForSeo(text: string): string {
  if (text.length <= SEO_DESCRIPTION_MAX_LENGTH) return text;
  const ellipsis = "…";
  const limit = SEO_DESCRIPTION_MAX_LENGTH - ellipsis.length;
  const cut = text.slice(0, limit);
  const lastSpace = cut.lastIndexOf(" ");
  const wordSafeCut = lastSpace > 0 ? cut.slice(0, lastSpace) : cut;
  return `${wordSafeCut}${ellipsis}`;
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
  const description = truncateForSeo(
    !isBlank(explicitDescription)
      ? explicitDescription
      : !isBlank(profile.description)
        ? profile.description
        : !isBlank(location)
          ? `${profile.name} — servicios profesionales en ${location}`
          : `${profile.name} — servicios profesionales`,
  );

  return {
    title,
    description,
    ...(website?.seo?.og_image ? { ogImage: { src: website.seo.og_image.url, alt: website.seo.og_image.alt } } : {}),
  };
}
