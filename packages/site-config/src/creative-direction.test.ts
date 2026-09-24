// A8.2.1 — WebsiteCreativeDirection contract (TypeScript side). The same
// fixtures/creative-direction.conformance.json is asserted by apps/api's
// tests/test_website_creative_direction.py against the Pydantic mirror, so
// the two implementations can only change together.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  CREATIVE_STRATEGIES,
  CTA_VARIANTS,
  DENSITY_SCALES,
  GALLERY_LAYOUTS,
  GALLERY_MAX_ITEMS_MAX,
  GALLERY_MAX_ITEMS_MIN,
  HERO_LAYOUTS,
  MOVABLE_SECTIONS,
  PALETTE_DERIVATIONS,
  PALETTE_MODES,
  RADIUS_SCALES,
  RATIONALE_MAX_LENGTH,
  SURFACE_MODES,
  TYPOGRAPHY_PAIRINGS,
  WEBSITE_CREATIVE_DIRECTION_VERSION,
  WEBSITE_DESIGN_FAMILIES,
  validateWebsiteCreativeDirection,
  type WebsiteCreativeDirection,
} from "./creative-direction.ts";

interface Conformance {
  vocabulary: Record<string, unknown>;
  valid: Record<string, unknown>;
  invalid: Record<string, unknown>;
}

const conformance = JSON.parse(
  readFileSync(new URL("../fixtures/creative-direction.conformance.json", import.meta.url), "utf-8"),
) as Conformance;

describe("WebsiteCreativeDirection — vocabulary matches the shared conformance fixture", () => {
  it("every exported enum/bound equals the fixture vocabulary", () => {
    expect({
      version: WEBSITE_CREATIVE_DIRECTION_VERSION,
      strategy: CREATIVE_STRATEGIES,
      family: WEBSITE_DESIGN_FAMILIES,
      "palette.mode": PALETTE_MODES,
      "palette.derivation": PALETTE_DERIVATIONS,
      "typography.pairing": TYPOGRAPHY_PAIRINGS,
      radius: RADIUS_SCALES,
      density: DENSITY_SCALES,
      sectionOrder: MOVABLE_SECTIONS,
      "hero.layout": HERO_LAYOUTS,
      "gallery.layout": GALLERY_LAYOUTS,
      "gallery.maxItems": { min: GALLERY_MAX_ITEMS_MIN, max: GALLERY_MAX_ITEMS_MAX },
      "surfaces.mode": SURFACE_MODES,
      "cta.variant": CTA_VARIANTS,
      "rationale.maxLength": RATIONALE_MAX_LENGTH,
    }).toEqual(conformance.vocabulary);
  });
});

describe("WebsiteCreativeDirection — valid directions", () => {
  it.each(Object.entries(conformance.valid))("accepts %s", (_name, direction) => {
    const result = validateWebsiteCreativeDirection(direction);
    expect(result).toEqual({ ok: true, value: direction });
  });

  it("covers preserve, evolve and new_direction", () => {
    for (const strategy of CREATIVE_STRATEGIES) {
      expect(conformance.valid[strategy]).toBeDefined();
    }
  });

  it("round-trips through JSON unchanged", () => {
    for (const direction of Object.values(conformance.valid)) {
      const reparsed = JSON.parse(JSON.stringify(direction)) as unknown;
      expect(validateWebsiteCreativeDirection(reparsed)).toEqual({ ok: true, value: direction });
    }
  });

  it("is expressible as the static WebsiteCreativeDirection type", () => {
    const direction: WebsiteCreativeDirection = {
      version: "1",
      strategy: "new_direction",
      family: "hospitality",
      palette: { mode: "brand_derived", derivation: "contrast_up" },
      typography: { pairing: "classic_serif" },
      radius: "sharp",
      density: "compact",
      sectionOrder: ["about", "services", "gallery"],
      hero: { layout: "centered" },
      gallery: { maxItems: 6, layout: "featured_grid" },
      surfaces: { mode: "flat" },
      cta: { variant: "emphasis" },
      rationale: "Editorial serif direction.",
    };
    expect(validateWebsiteCreativeDirection(direction).ok).toBe(true);
  });
});

describe("WebsiteCreativeDirection — invalid directions", () => {
  it.each(Object.entries(conformance.invalid))("rejects %s", (_name, direction) => {
    const result = validateWebsiteCreativeDirection(direction);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("WebsiteCreativeDirection — presentation-only boundary", () => {
  const evolve = conformance.valid.evolve as Record<string, unknown>;

  it.each([
    "businessName",
    "description",
    "services",
    "products",
    "prices",
    "address",
    "phone",
    "email",
    "whatsapp",
    "reviews",
    "testimonials",
    "rating",
    "projects",
    "claims",
    "stats",
    "html",
    "css",
    "style",
  ])("never accepts a %s field — business facts and markup come from BusinessConfig, never a direction", (field) => {
    const result = validateWebsiteCreativeDirection({ ...evolve, [field]: "anything" });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.join(" ")).toContain(`direction.${field}: unknown field`);
  });

  it.each(["provider", "model", "credits", "cost", "requestId"])(
    "never carries provider-specific %s — that belongs to CreativeGeneration metadata",
    (field) => {
      expect(validateWebsiteCreativeDirection({ ...evolve, [field]: "x" }).ok).toBe(false);
    },
  );

  it("has no field that can hold an asset URL or asset id", () => {
    const gallery = evolve.gallery as Record<string, unknown>;
    expect(validateWebsiteCreativeDirection({ ...evolve, gallery: { ...gallery, src: "https://x/y.jpg" } }).ok).toBe(false);
    expect(validateWebsiteCreativeDirection({ ...evolve, hero: { layout: "split", imageId: "a1" } }).ok).toBe(false);
  });

  it("the only free-text field is rationale, and it rejects markup", () => {
    expect(validateWebsiteCreativeDirection({ ...evolve, rationale: "<b>bold</b>" }).ok).toBe(false);
    expect(validateWebsiteCreativeDirection({ ...evolve, typography: { pairing: "Georgia, serif" } }).ok).toBe(false);
    expect(validateWebsiteCreativeDirection({ ...evolve, radius: "4px" }).ok).toBe(false);
  });
});
