// A8.2.3 — generateSiteConfig consumes a WebsiteCreativeDirection v1.
// Uses the REAL directions the internal provider derives
// (fixtures/internal-directions.json, drift-guarded by apps/api's
// tests/test_internal_directions_fixture.py) plus targeted directions for
// each individual field. Proves: every field has a SiteConfig consequence;
// EVOLVE vs NEW_DIRECTION differ materially in the SiteConfig itself; facts
// never change; output is deterministic; the rationale is never rendered.
// Also writes the directed SiteConfigs apps/api's real-build test builds
// and runs PlatformContract over (toMatchFileSnapshot).
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import {
  CREATIVE_STRATEGIES,
  HERO_LAYOUTS,
  PALETTE_DERIVATIONS,
  TYPOGRAPHY_PAIRINGS,
  WEBSITE_DESIGN_FAMILIES,
  validateWebsiteCreativeDirection,
  type BlockConfig,
  type MovableSection,
  type SiteConfig,
  type WebsiteCreativeDirection,
} from "@generate-web-ai/site-config";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { getDesignTokens } from "./design.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";
import { contrastRatio, deriveBrandPalette } from "./palette.ts";
import { DENSITY_SPACING, RADIUS_TOKENS, TYPOGRAPHY_STACKS } from "./presentation.ts";

interface DirectionCase {
  businessConfig: BusinessConfig;
  assets: BusinessAssetInput[];
  directions: Record<(typeof CREATIVE_STRATEGIES)[number], WebsiteCreativeDirection>;
}

const { cases } = JSON.parse(
  readFileSync(new URL("../fixtures/internal-directions.json", import.meta.url), "utf-8"),
) as { cases: Record<string, DirectionCase> };

const CASE_NAMES = Object.keys(cases);
const shop = cases.handmade_shop!;
const renovation = cases.renovation!;

function home(site: SiteConfig): BlockConfig[] {
  return site.pages[0]!.blocks;
}

function block<T extends BlockConfig["type"]>(site: SiteConfig, type: T): Extract<BlockConfig, { type: T }> | undefined {
  return home(site).find((b) => b.type === type) as Extract<BlockConfig, { type: T }> | undefined;
}

function galleryItems(site: SiteConfig) {
  return block(site, "gallery")?.content.items ?? [];
}

function sectionKey(b: BlockConfig): string {
  return b.id ?? b.type;
}

function withDirection(base: WebsiteCreativeDirection, patch: Partial<WebsiteCreativeDirection>): WebsiteCreativeDirection {
  const direction = { ...base, ...patch };
  const result = validateWebsiteCreativeDirection(direction);
  if (!result.ok) throw new Error(`test direction invalid: ${result.errors.join("; ")}`);
  return direction;
}

const evolveShop = shop.directions.evolve;

describe("every supplied direction is a valid canonical direction", () => {
  it.each(CASE_NAMES.flatMap((name) => CREATIVE_STRATEGIES.map((s) => [name, s] as const)))("%s / %s", (name, s) => {
    expect(validateWebsiteCreativeDirection(cases[name]!.directions[s]).ok).toBe(true);
  });
});

// B — family / palette ------------------------------------------------------

describe("palette resolution", () => {
  it.each(WEBSITE_DESIGN_FAMILIES)("family palette uses the %s family's own colours", (family) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { family, palette: { mode: "family" } }));
    expect(site.theme.colors).toEqual(getDesignTokens(family).colors);
  });

  it("brand palette keeps the business's real brand colours", () => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { palette: { mode: "brand" } }));
    expect(site.theme.colors).toEqual(shop.businessConfig.brand!.colors);
  });

  it.each(PALETTE_DERIVATIONS)("brand_derived:%s derives new, readable hex colours from the brand", (derivation) => {
    const site = generateSiteConfig(
      shop.businessConfig,
      shop.assets,
      withDirection(evolveShop, { palette: { mode: "brand_derived", derivation } }),
    );
    const colors = site.theme.colors;
    expect(colors).not.toEqual(shop.businessConfig.brand!.colors);
    for (const value of Object.values(colors)) expect(value).toMatch(/^#[0-9a-f]{6}$/);
    expect(contrastRatio(colors.foreground, colors.background)).toBeGreaterThanOrEqual(4.5);
  });

  it("each derivation is distinct", () => {
    const brand = shop.businessConfig.brand!.colors;
    const derived = PALETTE_DERIVATIONS.map((d) => JSON.stringify(deriveBrandPalette(brand, d)));
    expect(new Set(derived).size).toBe(PALETTE_DERIVATIONS.length);
  });

  it("falls back safely: no brand → family palette; non-hex brand → the brand's own colours", () => {
    const unbranded = { business_profile: shop.businessConfig.business_profile } as BusinessConfig;
    const derived = withDirection(evolveShop, { palette: { mode: "brand_derived", derivation: "vivid" } });
    expect(generateSiteConfig(unbranded, shop.assets, derived).theme.colors).toEqual(getDesignTokens(derived.family).colors);

    const named = {
      ...shop.businessConfig,
      brand: { ...shop.businessConfig.brand!, colors: { ...shop.businessConfig.brand!.colors, primary: "rebeccapurple" } },
    };
    expect(generateSiteConfig(named, shop.assets, derived).theme.colors).toEqual(named.brand.colors);
  });
});

// D / E / F — typography, radius, density ------------------------------------

describe("typography, radius and density tokens", () => {
  it.each(TYPOGRAPHY_PAIRINGS)("typography %s sets its safe local font stack", (pairing) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { typography: { pairing } }));
    expect(site.theme.fonts).toEqual(TYPOGRAPHY_STACKS[pairing]);
    expect(JSON.stringify(site.theme.fonts)).not.toMatch(/https?:|url\(/);
  });

  it("a preserve direction keeps the business's own brand typography", () => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, shop.directions.preserve);
    expect(site.theme.fonts.sans).toBe(shop.businessConfig.brand!.typography.sans);
  });

  it.each(["sharp", "soft", "round"] as const)("radius %s maps to its token", (radius) => {
    expect(generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { radius })).theme.radius).toEqual(
      RADIUS_TOKENS[radius],
    );
  });

  it("density: comfortable keeps today's spacing (no override); compact and airy set the section tokens", () => {
    const at = (density: "compact" | "comfortable" | "airy") =>
      generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { density })).theme.spacing;
    expect(at("comfortable")).toBeUndefined();
    expect(at("compact")).toEqual(DENSITY_SPACING.compact);
    expect(at("airy")).toEqual(DENSITY_SPACING.airy);
  });
});

// G — section order ----------------------------------------------------------

describe("section order", () => {
  const orders: MovableSection[][] = [
    ["services", "gallery", "about"],
    ["about", "gallery", "services"],
    ["gallery", "about", "services"],
  ];

  it.each(orders)("applies %s with hero first and cta+contact last", (...sectionOrder) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { sectionOrder }));
    expect(home(site).map(sectionKey)).toEqual(["hero", ...sectionOrder, "cta", "contact"]);
  });

  it("skips optional sections the business doesn't have, never inventing or dropping one", () => {
    const noPhotosNoAbout = {
      business_profile: { ...shop.businessConfig.business_profile, description: undefined, service_area: [] },
      brand: shop.businessConfig.brand,
    } as BusinessConfig;
    const site = generateSiteConfig(noPhotosNoAbout, [], withDirection(evolveShop, { sectionOrder: ["about", "gallery", "services"] }));
    expect(home(site).map(sectionKey)).toEqual(["hero", "services", "cta", "contact"]);
  });
});

// H / I / J / K / L — hero, gallery, surfaces, CTA ----------------------------

describe("hero, gallery, surfaces and CTA", () => {
  it.each(HERO_LAYOUTS)("hero layout %s is set on the hero content only", (layout) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { hero: { layout } }));
    const hero = block(site, "hero")!;
    expect(hero.content.layout).toBe(layout);
    expect(hero.content.heading).toBe(shop.businessConfig.business_profile.name);
  });

  it("caps the gallery after excluding the hero, keeping the original order", () => {
    const uncapped = generateSiteConfig(shop.businessConfig, shop.assets);
    const capped = generateSiteConfig(shop.businessConfig, shop.assets, shop.directions.new_direction);
    const heroSrc = block(capped, "hero")!.content.image!.src;

    expect(galleryItems(uncapped)).toHaveLength(37); // 38 photos − the hero
    expect(galleryItems(capped)).toHaveLength(6);
    expect(galleryItems(capped).map((i) => i.image.src)).toEqual(galleryItems(uncapped).slice(0, 6).map((i) => i.image.src));
    expect(galleryItems(capped).map((i) => i.image.src)).not.toContain(heroSrc);
  });

  it.each([3, 9, 24])("maxItems %i is respected", (maxItems) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { gallery: { maxItems, layout: "grid" } }));
    expect(galleryItems(site)).toHaveLength(Math.min(maxItems, 37));
  });

  it("real photos stay ahead of generated ones, unavailable ones stay out, duplicates appear once", () => {
    const assets: BusinessAssetInput[] = [
      { kind: "image", category: "gallery", origin: "generated", storage_url: "https://cdn.example.com/gen.jpg" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/a.jpg" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/b.jpg" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/b.jpg" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/c.jpg" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/x.jpg", unavailable_reason: "missing" },
    ];
    const site = generateSiteConfig(shop.businessConfig, assets, withDirection(evolveShop, { gallery: { maxItems: 3, layout: "grid" } }));
    // a.jpg becomes the hero; the gallery then takes b, c (deduped), then the generated one.
    expect(galleryItems(site).map((i) => i.image.src)).toEqual([
      "https://cdn.example.com/b.jpg",
      "https://cdn.example.com/c.jpg",
      "https://cdn.example.com/gen.jpg",
    ]);
  });

  it.each(["grid", "featured_grid"] as const)("gallery layout %s is set on the gallery content", (layout) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { gallery: { maxItems: 6, layout } }));
    expect(block(site, "gallery")!.content.layout).toBe(layout);
  });

  it("surfaces: alternate alternates base/surface; flat sets no section background", () => {
    const alternate = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { surfaces: { mode: "alternate" } }));
    const flat = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { surfaces: { mode: "flat" } }));
    const backgrounds = (site: SiteConfig) => home(site).filter((b) => !["hero", "cta", "contact"].includes(b.type)).map((b) => b.background);
    expect(backgrounds(alternate)).toEqual(["base", "surface", "base"]);
    expect(backgrounds(flat)).toEqual([undefined, undefined, undefined]);
    expect(home(flat).map((b) => b.id)).toEqual(home(alternate).map((b) => b.id));
  });

  it.each(["default", "emphasis"] as const)("CTA variant %s keeps the CTA's copy and destination", (variant) => {
    const site = generateSiteConfig(shop.businessConfig, shop.assets, withDirection(evolveShop, { cta: { variant } }));
    const cta = block(site, "cta")!;
    expect(cta.content.variant ?? "default").toBe(variant);
    expect(cta.content.primaryAction.href).toBe("#contact");
  });
});

// M / N — rationale never rendered, facts never change ------------------------

function facts(site: SiteConfig) {
  const content = (type: BlockConfig["type"]) => {
    const b = home(site).find((x) => x.type === type);
    if (!b) return undefined;
    const { layout: _layout, variant: _variant, items: _items, ...rest } = b.content as Record<string, unknown>;
    return rest;
  };
  return {
    brand: site.brand,
    seo: site.seo,
    business: site.business,
    whatsapp: site.whatsapp,
    features: site.features,
    legal: site.pages.slice(1),
    hero: content("hero"),
    services: block(site, "services")?.content,
    about: block(site, "features")?.content,
    cta: content("cta"),
    contact: block(site, "contact")?.content,
  };
}

describe("facts and rationale", () => {
  it.each(CASE_NAMES)("%s: every strategy renders identical facts, and only supplied photos", (name) => {
    const c = cases[name]!;
    const baseline = facts(generateSiteConfig(c.businessConfig, c.assets));
    const suppliedUrls = new Set(c.assets.map((a) => a.storage_url));
    for (const strategy of CREATIVE_STRATEGIES) {
      const site = generateSiteConfig(c.businessConfig, c.assets, c.directions[strategy]);
      expect(facts(site)).toEqual(baseline);
      for (const item of galleryItems(site)) expect(suppliedUrls.has(item.image.src as string)).toBe(true);
      const heroImage = block(site, "hero")!.content.image;
      if (heroImage) expect(suppliedUrls.has(heroImage.src as string)).toBe(true);
    }
  });

  it.each(CASE_NAMES)("%s: no generated content type (testimonials, faq, stats) is ever added", (name) => {
    const c = cases[name]!;
    for (const strategy of CREATIVE_STRATEGIES) {
      const site = generateSiteConfig(c.businessConfig, c.assets, c.directions[strategy]);
      const types = site.pages.flatMap((p) => p.blocks.map((b) => b.type));
      expect(types).not.toContain("testimonials");
      expect(types).not.toContain("faq");
      expect(block(site, "hero")!.content.stat).toBeUndefined();
    }
  });

  it.each(CASE_NAMES)("%s: the direction's rationale never appears in the site", (name) => {
    const c = cases[name]!;
    for (const strategy of CREATIVE_STRATEGIES) {
      const serialized = JSON.stringify(generateSiteConfig(c.businessConfig, c.assets, c.directions[strategy]));
      expect(serialized).not.toContain(c.directions[strategy].rationale);
      expect(serialized).not.toContain("rationale");
    }
  });
});

// O / P — determinism, material EVOLVE vs NEW_DIRECTION difference -------------

describe("determinism and Refresh vs New direction", () => {
  it.each(CASE_NAMES)("%s: same inputs + same direction → identical SiteConfig", (name) => {
    const c = cases[name]!;
    for (const strategy of CREATIVE_STRATEGIES) {
      const first = generateSiteConfig(c.businessConfig, c.assets, c.directions[strategy]);
      const second = generateSiteConfig(structuredClone(c.businessConfig), structuredClone(c.assets), structuredClone(c.directions[strategy]));
      expect(JSON.stringify(second)).toBe(JSON.stringify(first));
    }
  });

  it.each(CASE_NAMES)("%s: EVOLVE and NEW_DIRECTION produce materially different SiteConfigs", (name) => {
    const c = cases[name]!;
    const evolve = generateSiteConfig(c.businessConfig, c.assets, c.directions.evolve);
    const next = generateSiteConfig(c.businessConfig, c.assets, c.directions.new_direction);

    expect(next.theme.colors).not.toEqual(evolve.theme.colors);
    expect(next.theme.fonts).not.toEqual(evolve.theme.fonts);
    expect(next.theme.spacing).not.toEqual(evolve.theme.spacing);
    expect(home(next).map(sectionKey)).not.toEqual(home(evolve).map(sectionKey));
    expect(block(next, "hero")!.content.layout).not.toBe(block(evolve, "hero")!.content.layout);
    expect(galleryItems(next).length).toBeLessThan(galleryItems(evolve).length);
    expect(block(next, "gallery")!.content.layout).not.toBe(block(evolve, "gallery")!.content.layout);
    // …while every fact stays the same.
    expect(facts(next)).toEqual(facts(evolve));
  });

  it("handmade shop: the new direction's CTA is emphasized where the refresh keeps the default", () => {
    const evolve = generateSiteConfig(shop.businessConfig, shop.assets, shop.directions.evolve);
    const next = generateSiteConfig(shop.businessConfig, shop.assets, shop.directions.new_direction);
    expect(block(evolve, "cta")!.content.variant ?? "default").toBe("default");
    expect(block(next, "cta")!.content.variant).toBe("emphasis");
  });

  it("renovation new direction is distinctly different from today's no-direction site", () => {
    const today = generateSiteConfig(renovation.businessConfig, renovation.assets);
    const next = generateSiteConfig(renovation.businessConfig, renovation.assets, renovation.directions.new_direction);
    expect(home(next).map(sectionKey)).not.toEqual(home(today).map(sectionKey));
    expect(next.theme).not.toEqual(today.theme);
  });
});

// Real-build fixtures for apps/api (Q / R / S) ---------------------------------

describe("directed SiteConfig fixtures for the backend real-build test", () => {
  it("are up to date with the generator", async () => {
    const output = Object.fromEntries(
      CASE_NAMES.map((name) => {
        const c = cases[name]!;
        return [
          name,
          {
            evolve: generateSiteConfig(c.businessConfig, c.assets, c.directions.evolve),
            new_direction: generateSiteConfig(c.businessConfig, c.assets, c.directions.new_direction),
          },
        ];
      }),
    );
    await expect(`${JSON.stringify(output, null, 2)}\n`).toMatchFileSnapshot(
      "../../../apps/api/tests/fixtures/a8_directed_site_configs.json",
    );
  });
});
