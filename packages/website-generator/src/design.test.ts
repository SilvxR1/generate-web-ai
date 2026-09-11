import { describe, expect, it } from "vitest";
import { getDesignTokens, resolveDesignFamily } from "./design.ts";

describe("resolveDesignFamily", () => {
  it("maps a known vertical straight to its family", () => {
    expect(resolveDesignFamily("home_renovation", undefined)).toBe("construction");
    expect(resolveDesignFamily("clinic", undefined)).toBe("professional_services");
    expect(resolveDesignFamily("restaurant", undefined)).toBe("hospitality");
  });

  it("a known vertical's family is never overridden by visual_style keywords", () => {
    // Regression: the reforma-valencia fixture's real visual_style is
    // "warm, mediterranean, editorial" — "warm" alone must not flip a
    // renovation business into the artisan family.
    expect(resolveDesignFamily("home_renovation", "warm, mediterranean, editorial")).toBe("construction");
  });

  it("uses visual_style to disambiguate the ambiguous 'other' vertical", () => {
    expect(resolveDesignFamily("other", "hecho a mano, artesanal, cálido")).toBe("artisan");
    expect(resolveDesignFamily("other", "handmade crochet amigurumi")).toBe("artisan");
  });

  it("uses visual_style to disambiguate the ambiguous 'ecommerce' vertical", () => {
    expect(resolveDesignFamily("ecommerce", "boutique, artisan, organic")).toBe("artisan");
  });

  it("falls back to generic when the vertical is ambiguous and visual_style gives no signal", () => {
    expect(resolveDesignFamily("other", undefined)).toBe("generic");
    expect(resolveDesignFamily("ecommerce", "sleek and modern")).toBe("generic");
  });

  it("is a pure, deterministic function of its inputs", () => {
    const a = resolveDesignFamily("home_renovation", "warm");
    const b = resolveDesignFamily("home_renovation", "warm");
    expect(a).toBe(b);
  });
});

describe("getDesignTokens", () => {
  it("returns materially different color palettes across families", () => {
    const artisan = getDesignTokens("artisan");
    const construction = getDesignTokens("construction");
    const professional = getDesignTokens("professional_services");

    expect(artisan.colors).not.toEqual(construction.colors);
    expect(artisan.colors).not.toEqual(professional.colors);
    expect(construction.colors).not.toEqual(professional.colors);
  });

  it("returns materially different radius/typography/composition tokens across families", () => {
    const artisan = getDesignTokens("artisan");
    const construction = getDesignTokens("construction");

    expect(artisan.radius).not.toEqual(construction.radius);
    expect(artisan.fonts).not.toEqual(construction.fonts);
    expect(artisan.ctaVariant).not.toBe(construction.ctaVariant);
    expect(artisan.galleryPlacement).not.toBe(construction.galleryPlacement);
  });
});
