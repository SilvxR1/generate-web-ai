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
import type {
  BlockConfig,
  GalleryBlockConfig,
  HeroBlockConfig,
  MovableSection,
  PageConfig,
  SiteConfig,
  WebsiteCreativeDirection,
} from "@generate-web-ai/site-config";
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
import { buildLegalPages } from "./legal.ts";
import { getPreset } from "./presets.ts";
import { resolvePresentation } from "./presentation.ts";
import { buildSeo } from "./seo.ts";

/**
 * `direction` (A8.2.3, optional) is a validated WebsiteCreativeDirection v1
 * (see @generate-web-ai/site-config). It changes only HOW the same real
 * content is presented (see presentation.ts' resolvePresentation). Omitted,
 * the output is exactly what this function produced before directions
 * existed; fixtures/no-direction-golden.json guards that.
 */
export function generateSiteConfig(
  businessConfig: BusinessConfig,
  assets: readonly BusinessAssetInput[] = [],
  direction?: WebsiteCreativeDirection,
): SiteConfig {
  const {
    business_profile: profile,
    brand,
    website,
    lead_management: leadManagement,
    legal_profile: legalProfile,
    whatsapp: whatsappConfig,
  } = businessConfig;

  const realGalleryAssetCount = selectGalleryAssets(assets).length;
  const presentation = resolvePresentation(businessConfig, realGalleryAssetCount, direction);
  // Copy (section headings, CTA wording) follows the business's own content
  // family, never a direction's family.
  const preset = getPreset(profile.industry, presentation.contentFamily);

  // Real assets always take priority over a generated/text substitute
  // for the same role (LR-05). A business's own manually-entered
  // `brand.logo` is still a real, human-provided fact — used only when
  // no uploaded/imported BusinessAsset fills the logo role.
  const logoAsset = selectLogoAsset(assets);
  const heroAsset = selectHeroAsset(assets);
  let galleryAssets = selectGalleryAssets(assets, heroAsset ? new Set([heroAsset.storage_url]) : undefined);
  if (presentation.gallery.maxItems !== undefined) {
    // A direction's gallery cap applies after the hero photo is excluded,
    // keeps the existing real-before-generated order, and never shows the
    // same file twice. Assets themselves are never modified.
    const seen = new Set<string>();
    galleryAssets = galleryAssets
      .filter((asset) => !seen.has(asset.storage_url) && seen.add(asset.storage_url))
      .slice(0, presentation.gallery.maxItems);
  }

  const customerFacingDescription = sanitizeCustomerCopy(profile.description);

  // Built first so the hero/CTA only link to "#contact" when that
  // section will actually be rendered — never a dangling in-page anchor.
  const contactBlock = buildContactBlock(profile, leadManagement, preset, whatsappConfig);

  const heroBlock: HeroBlockConfig = buildHeroBlock(
    profile,
    preset,
    customerFacingDescription,
    heroAsset,
    contactBlock !== null,
  );
  if (presentation.heroLayout) heroBlock.content.layout = presentation.heroLayout;

  const galleryBlock: GalleryBlockConfig | null = buildGalleryBlock(galleryAssets, preset, profile.name);
  if (galleryBlock && presentation.gallery.layout) galleryBlock.content.layout = presentation.gallery.layout;

  const optionalSections: Record<MovableSection, BlockConfig | null> = {
    services: buildServicesBlock(profile, preset),
    gallery: galleryBlock,
    about: buildAboutBlock(profile, preset, customerFacingDescription),
  };

  // Hero first, then only the optional sections that actually exist, in the
  // resolved order, then the cta/contact conversion pair.
  const blocks: BlockConfig[] = [heroBlock];
  for (const section of presentation.sectionOrder) {
    const block = optionalSections[section];
    if (block) blocks.push(block);
  }
  if (contactBlock) {
    blocks.push(buildCtaBlock(profile, preset, presentation.ctaVariant));
    blocks.push(contactBlock);
  }

  if (presentation.alternateSurfaces) {
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
    theme: presentation.theme,
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
