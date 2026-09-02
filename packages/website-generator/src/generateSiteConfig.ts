/**
 * BusinessConfig -> SiteConfig, deterministically. No AI: a fixed,
 * preset-driven mapping (see presets.ts) from real BusinessConfig facts
 * onto the *existing* website engine's schema
 * (@generate-web-ai/site-config) and blocks
 * (@generate-web-ai/blocks, via @generate-web-ai/renderer) — this file
 * produces data, never a second schema or a client-specific code path.
 *
 * Hard rule enforced throughout this module and blocks.ts: every piece
 * of generated content either comes directly from a BusinessConfig
 * field, or is generic template copy that asserts nothing about the
 * specific business (no invented testimonials, project counts, ratings,
 * certifications, or years of experience — see blocks.ts's Hero
 * docstring for the one field, `stat`, that exists specifically to hold
 * that kind of claim and is never populated here).
 */
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { BlockConfig, PageConfig, SiteConfig } from "@generate-web-ai/site-config";
import {
  buildAboutBlock,
  buildContactBlock,
  buildCtaBlock,
  buildHeroBlock,
  buildServicesBlock,
} from "./blocks.ts";
import { buildBusiness } from "./business.ts";
import { getPreset } from "./presets.ts";
import { buildSeo } from "./seo.ts";
import { DEFAULT_THEME } from "./theme.ts";

export function generateSiteConfig(businessConfig: BusinessConfig): SiteConfig {
  const { business_profile: profile, brand, website, lead_management: leadManagement } = businessConfig;
  const preset = getPreset(profile.industry);

  const blocks: BlockConfig[] = [buildHeroBlock(profile, preset)];

  const servicesBlock = buildServicesBlock(profile, preset);
  if (servicesBlock) blocks.push(servicesBlock);

  const aboutBlock = buildAboutBlock(profile, preset);
  if (aboutBlock) blocks.push(aboutBlock);

  blocks.push(buildCtaBlock(profile, preset));

  const contactBlock = buildContactBlock(profile, leadManagement, preset);
  if (contactBlock) blocks.push(contactBlock);

  const page: PageConfig = { path: "/", blocks };
  const business = buildBusiness(profile);

  return {
    brand: {
      name: profile.name,
      ...(brand?.tagline ? { tagline: brand.tagline } : {}),
    },
    // BrandTypography (BusinessConfig) and ThemeFontConfig
    // (site-config) share the same field names (sans/display) by
    // design — see brand.py's docstring — so this is otherwise a direct
    // passthrough. The one wrinkle: Pydantic's `display: str | None`
    // serializes an omitted value as JSON `null`, while ThemeFontConfig
    // (TypeScript) expects `display?: string` (`undefined`, never
    // `null`) — normalized here, not a real semantic difference.
    theme: brand
      ? {
          colors: brand.colors,
          fonts: { sans: brand.typography.sans, display: brand.typography.display ?? undefined },
          radius: DEFAULT_THEME.radius,
        }
      : DEFAULT_THEME,
    pages: [page],
    features: {
      contactForm: Boolean(contactBlock?.content.form),
      chatbot: false,
      booking: false,
    },
    seo: buildSeo(profile, website, preset),
    ...(business ? { business } : {}),
  };
}
