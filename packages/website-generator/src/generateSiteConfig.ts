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
 *
 * `assets` (optional, defaults to none) is a business's real
 * BusinessAsset rows — see assets.ts for the selection rules that turn
 * them into a brand logo, a hero image, and a gallery, and design.ts for
 * the deterministic per-business-family visual variation (LR-07)
 * layered on top of them. Both are additive: a business with no assets
 * and default creative direction produces exactly what this module
 * always produced.
 */
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { BlockConfig, PageConfig, SiteConfig } from "@generate-web-ai/site-config";
import type { BusinessAssetInput } from "./assets.ts";
import { selectGalleryAssets, selectHeroAsset, selectLogoAsset } from "./assets.ts";
import {
  buildAboutBlock,
  buildContactBlock,
  buildCtaBlock,
  buildGalleryBlock,
  buildHeroBlock,
  buildServicesBlock,
  buildWhatsAppConfig,
} from "./blocks.ts";
import { buildBusiness } from "./business.ts";
import { sanitizeCustomerCopy } from "./copy.ts";
import { getDesignTokens, resolveDesignFamily } from "./design.ts";
import { buildLegalPages } from "./legal.ts";
import { getPreset } from "./presets.ts";
import { buildSeo } from "./seo.ts";

export function generateSiteConfig(businessConfig: BusinessConfig, assets: readonly BusinessAssetInput[] = []): SiteConfig {
  const {
    business_profile: profile,
    brand,
    website,
    lead_management: leadManagement,
    legal_profile: legalProfile,
    whatsapp: whatsappConfig,
  } = businessConfig;

  const realGalleryAssetCount = selectGalleryAssets(assets).length;
  const family = resolveDesignFamily(profile.industry, brand?.visual_style, realGalleryAssetCount);
  const tokens = getDesignTokens(family);
  const preset = getPreset(profile.industry, family);

  // Real assets always take priority over a generated/text substitute
  // for the same role (LR-05). A business's own manually-entered
  // `brand.logo` is still a real, human-provided fact — used only when
  // no uploaded/imported BusinessAsset fills the logo role.
  const logoAsset = selectLogoAsset(assets);
  const heroAsset = selectHeroAsset(assets);
  const galleryAssets = selectGalleryAssets(assets, heroAsset ? new Set([heroAsset.storage_url]) : undefined);

  const customerFacingDescription = sanitizeCustomerCopy(profile.description);

  const blocks: BlockConfig[] = [buildHeroBlock(profile, preset, customerFacingDescription, heroAsset)];

  const servicesBlock = buildServicesBlock(profile, preset);
  if (servicesBlock) blocks.push(servicesBlock);

  const galleryBlock = buildGalleryBlock(galleryAssets, preset, profile.name);
  if (galleryBlock && tokens.galleryPlacement === "after_services") blocks.push(galleryBlock);

  const aboutBlock = buildAboutBlock(profile, preset, customerFacingDescription);
  if (aboutBlock) blocks.push(aboutBlock);

  if (galleryBlock && tokens.galleryPlacement === "after_about") blocks.push(galleryBlock);

  blocks.push(buildCtaBlock(profile, preset, tokens.ctaVariant));

  const contactBlock = buildContactBlock(profile, leadManagement, preset, whatsappConfig);
  if (contactBlock) blocks.push(contactBlock);

  if (galleryBlock && tokens.galleryPlacement === "after_hero") {
    blocks.splice(1, 0, galleryBlock);
  }

  if (tokens.alternateSurfaces) {
    let surfaceToggle = false;
    for (const block of blocks) {
      if (block.type === "hero" || block.type === "cta" || block.type === "contact") continue;
      block.background = surfaceToggle ? "surface" : "base";
      surfaceToggle = !surfaceToggle;
    }
  }

  const siteWhatsappConfig = buildWhatsAppConfig(whatsappConfig);

  const page: PageConfig = { path: "/", blocks };
  const legalPages = buildLegalPages(profile, legalProfile ?? undefined, Boolean(contactBlock?.content.form));
  const business = buildBusiness(profile);

  return {
    brand: {
      name: profile.name,
      ...(brand?.tagline ? { tagline: brand.tagline } : {}),
      ...(logoAsset
        ? { logo: { src: logoAsset.storage_url, alt: logoAsset.alt_text?.trim() || `Logo de ${profile.name}` } }
        : brand?.logo
          ? { logo: { src: brand.logo.url, alt: brand.logo.alt } }
          : {}),
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
          radius: tokens.radius,
        }
      : { colors: tokens.colors, fonts: tokens.fonts, radius: tokens.radius },
    pages: [page, ...legalPages],
    features: {
      contactForm: Boolean(contactBlock?.content.form),
      chatbot: false,
      booking: false,
    },
    seo: buildSeo(profile, website, customerFacingDescription),
    ...(business ? { business } : {}),
    ...(siteWhatsappConfig ? { whatsapp: siteWhatsappConfig } : {}),
  };
}
