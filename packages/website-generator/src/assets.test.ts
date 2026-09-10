import { describe, expect, it } from "vitest";
import { assetToImageConfig, selectGalleryAssets, selectHeroAsset, selectLogoAsset, type BusinessAssetInput } from "./assets.ts";

function asset(overrides: Partial<BusinessAssetInput> = {}): BusinessAssetInput {
  return {
    kind: "image",
    category: "gallery",
    origin: "uploaded",
    storage_url: "https://api.example.com/uploads/biz/photo.jpg",
    alt_text: null,
    ...overrides,
  };
}

describe("selectLogoAsset", () => {
  it("returns undefined when there is no logo asset", () => {
    expect(selectLogoAsset([asset({ category: "gallery" })])).toBeUndefined();
  });

  it("picks an asset with kind=logo", () => {
    const logo = asset({ kind: "logo", category: "other" });
    expect(selectLogoAsset([asset({ category: "gallery" }), logo])).toBe(logo);
  });

  it("picks an asset categorized logo even if kind is generic image", () => {
    const logo = asset({ kind: "image", category: "logo" });
    expect(selectLogoAsset([logo])).toBe(logo);
  });

  it("prefers an uploaded logo over a generated one", () => {
    const generated = asset({ kind: "logo", origin: "generated", storage_url: "https://x/gen.png" });
    const uploaded = asset({ kind: "logo", origin: "uploaded", storage_url: "https://x/real.png" });
    expect(selectLogoAsset([generated, uploaded])).toBe(uploaded);
  });

  it("never falls back to a non-logo asset", () => {
    const product = asset({ kind: "image", category: "product" });
    expect(selectLogoAsset([product])).toBeUndefined();
  });

  it("excludes low_quality assets", () => {
    const logo = asset({ kind: "logo", category: "low_quality" });
    expect(selectLogoAsset([logo])).toBeUndefined();
  });
});

describe("selectHeroAsset", () => {
  it("prefers a hero_candidate over any other gallery-worthy image", () => {
    const gallery = asset({ category: "gallery", storage_url: "https://x/gallery.jpg" });
    const hero = asset({ category: "hero_candidate", storage_url: "https://x/hero.jpg" });
    expect(selectHeroAsset([gallery, hero])).toBe(hero);
  });

  it("falls back to the first gallery-worthy image when no hero_candidate exists", () => {
    const product = asset({ category: "product", storage_url: "https://x/product.jpg" });
    expect(selectHeroAsset([product])).toBe(product);
  });

  it("returns undefined when there are no real images", () => {
    expect(selectHeroAsset([])).toBeUndefined();
  });

  it("never picks the logo as the hero image", () => {
    const logo = asset({ kind: "logo", category: "logo" });
    expect(selectHeroAsset([logo])).toBeUndefined();
  });
});

describe("selectGalleryAssets", () => {
  it("returns every gallery-worthy image, excluding the hero image", () => {
    const hero = asset({ category: "hero_candidate", storage_url: "https://x/hero.jpg" });
    const product = asset({ category: "product", storage_url: "https://x/product.jpg" });
    const project = asset({ category: "project", storage_url: "https://x/project.jpg" });

    const gallery = selectGalleryAssets([hero, product, project], new Set([hero.storage_url]));
    expect(gallery.map((a) => a.storage_url)).toEqual(["https://x/project.jpg", "https://x/product.jpg"]);
  });

  it("excludes non-image kinds and low-quality assets", () => {
    const video = asset({ kind: "video", category: "project" });
    const lowQuality = asset({ category: "low_quality" });
    expect(selectGalleryAssets([video, lowQuality])).toEqual([]);
  });
});

describe("assetToImageConfig", () => {
  it("uses the asset's own alt text when present", () => {
    const result = assetToImageConfig(asset({ alt_text: "Bufanda tejida a mano" }), "fallback");
    expect(result.alt).toBe("Bufanda tejida a mano");
  });

  it("falls back to the provided alt when the asset has none", () => {
    const result = assetToImageConfig(asset({ alt_text: null }), "Foto de Cositas y Puntos");
    expect(result.alt).toBe("Foto de Cositas y Puntos");
  });
});
