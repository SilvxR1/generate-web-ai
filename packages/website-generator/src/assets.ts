/**
 * BusinessAsset -> AssetConfig — the missing link that used to make every
 * real uploaded logo/photo stop at the API boundary and never reach a
 * generated SiteConfig (Launch Readiness LR-05). `generateSiteConfig()`
 * previously took only a `BusinessConfig`, so a business's real assets
 * (app.db.models.business_asset.BusinessAsset, fetched in Studio via
 * `listBusinessAssets`) had no way in. This module is the deterministic,
 * no-AI selection logic that picks which real asset fills which role
 * (brand logo, hero image, gallery items) — never a placeholder/generated
 * substitute when a real one exists for the same role (Section 1 / LR-05's
 * "real assets always take priority" rule).
 */
import type { AssetConfig } from "@generate-web-ai/site-config";

/**
 * Structural shape apps/studio's `BusinessAsset` (and
 * app.db.models.business_asset.BusinessAsset) already satisfies. Declared
 * independently, the same "Protocol, not an import" boundary
 * app.domain.creative.brief.AssetInput already uses on the Python side —
 * this package stays framework/ORM-agnostic.
 */
export interface BusinessAssetInput {
  kind: "logo" | "image" | "video" | "document";
  category:
    | "logo"
    | "project"
    | "team"
    | "facility"
    | "product"
    | "before"
    | "after"
    | "hero_candidate"
    | "gallery"
    | "other"
    | "low_quality";
  origin: "uploaded" | "imported" | "generated";
  storage_url: string;
  alt_text?: string | null;
}

const GALLERY_CATEGORIES = new Set(["gallery", "project", "product", "before", "after", "team", "facility"]);

/** Real, human-provided content outranks anything a creative provider
 * generated for the same role — never the reverse. */
function originRank(origin: BusinessAssetInput["origin"]): number {
  return origin === "generated" ? 0 : 1;
}

function usable(assets: readonly BusinessAssetInput[]): BusinessAssetInput[] {
  return assets.filter((asset) => asset.category !== "low_quality" && asset.storage_url.trim().length > 0);
}

function toAssetConfig(asset: BusinessAssetInput, fallbackAlt: string): AssetConfig {
  const alt = asset.alt_text?.trim() || fallbackAlt;
  return { src: asset.storage_url, alt };
}

/** The business's real logo, if it has one — kind `logo` (category is a
 * secondary signal only; a business may not have re-categorized an
 * uploaded logo yet). Prefers a real upload/import over a generated
 * placeholder for the same role. Never falls back to a non-logo image:
 * an unrelated product photo is not a logo. */
export function selectLogoAsset(assets: readonly BusinessAssetInput[]): BusinessAssetInput | undefined {
  const candidates = usable(assets).filter((asset) => asset.kind === "logo" || asset.category === "logo");
  if (candidates.length === 0) return undefined;
  return [...candidates].sort((a, b) => originRank(b.origin) - originRank(a.origin))[0];
}

/** The single best image for the hero section, if any real photography
 * exists. `hero_candidate` (a human's explicit choice) wins outright;
 * otherwise the first gallery-worthy image stands in — still real
 * content, never a generated/stock substitute while a real option
 * exists. */
export function selectHeroAsset(
  assets: readonly BusinessAssetInput[],
  excludeUrls: ReadonlySet<string> = new Set(),
): BusinessAssetInput | undefined {
  const pool = usable(assets)
    .filter((asset) => asset.kind === "image" && !excludeUrls.has(asset.storage_url))
    .sort((a, b) => originRank(b.origin) - originRank(a.origin));

  const heroCandidate = pool.find((asset) => asset.category === "hero_candidate");
  if (heroCandidate) return heroCandidate;

  return pool.find((asset) => GALLERY_CATEGORIES.has(asset.category));
}

/** Every remaining real photo worth showing in a gallery/portfolio grid,
 * real content preferred over generated for the same category, hero
 * image excluded so it isn't shown twice. Ordered by category (project
 * work first, then product/team/facility) so a before/after pair stays
 * adjacent. */
export function selectGalleryAssets(
  assets: readonly BusinessAssetInput[],
  excludeUrls: ReadonlySet<string> = new Set(),
): BusinessAssetInput[] {
  const CATEGORY_ORDER: BusinessAssetInput["category"][] = [
    "project",
    "gallery",
    "product",
    "before",
    "after",
    "team",
    "facility",
  ];

  return usable(assets)
    .filter(
      (asset) => asset.kind === "image" && !excludeUrls.has(asset.storage_url) && GALLERY_CATEGORIES.has(asset.category),
    )
    .sort((a, b) => {
      const rankDiff = originRank(b.origin) - originRank(a.origin);
      if (rankDiff !== 0) return rankDiff;
      return CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category);
    });
}

export function assetToImageConfig(asset: BusinessAssetInput, fallbackAlt: string): AssetConfig {
  return toAssetConfig(asset, fallbackAlt);
}
