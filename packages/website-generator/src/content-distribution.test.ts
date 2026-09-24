// A8.3.2 — content distribution. The hero shows SELECTED existing text
// (a real tagline, or one whole sentence of the sanitized description),
// About keeps the full description, a one-sentence description is never
// shown twice, and gallery items only carry text that adds information.
// Nothing here writes new copy: every assertion about text checks that it
// is an exact substring of the business's own source text.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { BlockConfig, SiteConfig, WebsiteCreativeDirection } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { HERO_SENTENCE_MAX_LENGTH, sanitizeCustomerCopy, selectHeroSupportingCopy } from "./copy.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";

const LONG_DESCRIPTION =
  "Taller familiar de piezas de ganchillo hechas a mano en Valencia. " +
  "Creamos muñecos, llaveros y decoración infantil por encargo, con lanas de algodón. " +
  "Cada pieza se diseña y se teje una a una, respetando los tiempos de cada proyecto. " +
  "Enviamos a toda España y preparamos packs de regalo para cumpleaños y bautizos.";

function photos(n: number, category: BusinessAssetInput["category"] = "gallery"): BusinessAssetInput[] {
  return Array.from({ length: n }, (_, i) => ({
    kind: "image",
    category,
    origin: "uploaded",
    storage_url: `https://cdn.example.com/${category}-${i}.jpg`,
    alt_text: null,
  }));
}

const handmade: BusinessConfig = {
  business_profile: {
    industry: "other",
    name: "Taller Ovillo",
    slug: "taller-ovillo",
    description: LONG_DESCRIPTION,
    location: { city: "Valencia", country: "ES" },
    services: [
      { id: "encargos", name: "Encargos personalizados", description: "Piezas únicas bajo pedido." },
      { id: "regalos", name: "Packs de regalo", description: "Cajas preparadas para regalar." },
    ],
    contact: { phone: "+34 600 111 222", email: "hola@example.com", whatsapp: "+34600111222" },
    target_customers: "Familias que buscan regalos hechos a mano.",
  },
  lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
} as BusinessConfig;

const NEW_DIRECTION: WebsiteCreativeDirection = {
  version: "1",
  strategy: "new_direction",
  family: "hospitality",
  palette: { mode: "family" },
  typography: { pairing: "classic_serif" },
  radius: "soft",
  density: "compact",
  sectionOrder: ["about", "gallery", "services"],
  hero: { layout: "centered" },
  gallery: { maxItems: 6, layout: "grid" },
  surfaces: { mode: "flat" },
  cta: { variant: "emphasis" },
  rationale: "A distinctly different presentation.",
};

const blocks = (site: SiteConfig): BlockConfig[] => site.pages[0]!.blocks;
const hero = (site: SiteConfig) => blocks(site).find((b) => b.type === "hero")!.content as { subheading?: string };
const about = (site: SiteConfig) => blocks(site).find((b) => b.type === "features")?.content as { subheading?: string } | undefined;
const gallery = (site: SiteConfig) =>
  (blocks(site).find((b) => b.type === "gallery")?.content as { items: Record<string, unknown>[] } | undefined)?.items ?? [];

describe("selectHeroSupportingCopy", () => {
  it("prefers the real tagline, verbatim (trimmed only)", () => {
    expect(selectHeroSupportingCopy("  Hecho a mano, pieza a pieza  ", LONG_DESCRIPTION)).toEqual({
      text: "Hecho a mano, pieza a pieza",
      source: "tagline",
    });
  });

  it("otherwise takes the first whole sentence of the sanitized description", () => {
    expect(selectHeroSupportingCopy(undefined, LONG_DESCRIPTION)).toEqual({
      text: "Taller familiar de piezas de ganchillo hechas a mano en Valencia.",
      source: "description_sentence",
    });
  });

  it("never cuts or substitutes a first sentence longer than the bound", () => {
    const longFirst = `${"Una frase muy larga sin puntos intermedios ".repeat(6).trim()}. Segunda frase corta.`;
    expect(longFirst.split(". ")[0]!.length).toBeGreaterThan(HERO_SENTENCE_MAX_LENGTH);
    expect(selectHeroSupportingCopy(undefined, longFirst)).toEqual({ source: "none" });
  });

  it("returns none for a missing/blank description and a blank tagline", () => {
    expect(selectHeroSupportingCopy("   ", undefined)).toEqual({ source: "none" });
  });
});

describe("hero / about distribution — realistic long description, no tagline, untitled photos", () => {
  for (const [label, direction] of [["undirected", undefined], ["new direction", NEW_DIRECTION]] as const) {
    it(`${label}: hero is one existing whole sentence; About keeps the full cleaned description`, () => {
      const site = generateSiteConfig(handmade, photos(12), direction);
      const heroCopy = hero(site).subheading!;
      const full = sanitizeCustomerCopy(LONG_DESCRIPTION)!;

      expect(heroCopy.length).toBeLessThan(full.length / 2);
      expect(full.startsWith(heroCopy)).toBe(true); // exact existing text, whole first sentence
      expect(heroCopy).toMatch(/[.!?]$/);
      expect(about(site)?.subheading).toBe(full);
      expect(heroCopy).not.toBe(about(site)?.subheading);
    });
  }

  it("the gallery keeps the A8.2 cap and the same deterministic photos, with no manufactured titles", () => {
    const items = gallery(generateSiteConfig(handmade, photos(12), NEW_DIRECTION));

    expect(items).toHaveLength(6);
    expect(items.map((i) => (i.image as { src: string }).src)).toEqual(
      photos(12).slice(1, 7).map((p) => p.storage_url), // photo 0 is the hero
    );
    for (const item of items) {
      expect(item.title).toBeUndefined();
      expect(item.category).toBeUndefined(); // one category across every photo: no information
    }
  });
});

describe("tagline and short-description edge cases", () => {
  it("uses the exact real tagline, without appending description text; About keeps the description", () => {
    const tagline = "Ganchillo con cariño desde Valencia";
    const withTagline = {
      ...handmade,
      brand: {
        tagline,
        colors: { primary: "#111111", secondary: "#222222", accent: "#333333", background: "#ffffff", foreground: "#000000" },
        typography: { sans: "Inter, sans-serif" },
      },
    } as BusinessConfig;
    const site = generateSiteConfig(withTagline, photos(3));

    expect(hero(site).subheading).toBe(tagline);
    expect(about(site)?.subheading).toBe(sanitizeCustomerCopy(LONG_DESCRIPTION));
  });

  it("a one-sentence description is shown once (in the hero); About keeps its other real facts", () => {
    const short = {
      ...handmade,
      business_profile: { ...handmade.business_profile, description: "Piezas de ganchillo hechas a mano." },
    } as BusinessConfig;
    const site = generateSiteConfig(short, photos(3));

    expect(hero(site).subheading).toBe("Piezas de ganchillo hechas a mano.");
    expect(about(site)?.subheading).toBeUndefined();
    expect(JSON.stringify(about(site))).toContain("Familias que buscan regalos hechos a mano."); // target_customers kept
  });

  it("a one-sentence description with no other About facts omits the empty About section entirely", () => {
    const onlySentence = {
      business_profile: { industry: "other", name: "Taller Ovillo", slug: "taller-ovillo", description: "Piezas de ganchillo." },
    } as BusinessConfig;
    const site = generateSiteConfig(onlySentence, []);

    expect(hero(site).subheading).toBe("Piezas de ganchillo.");
    expect(blocks(site).some((b) => b.type === "features")).toBe(false);
  });

  it("no description keeps the existing preset line in the hero (unchanged behaviour)", () => {
    const none = {
      business_profile: { industry: "home_renovation", name: "Reformas Sur", slug: "reformas-sur" },
    } as BusinessConfig;
    expect(hero(generateSiteConfig(none, [])).subheading).toBe("Reformas integrales y servicios para el hogar.");
  });
});

describe("gallery metadata rule", () => {
  it("shows the real category badge only when the displayed photos span several categories", () => {
    const mixed = [...photos(2, "before"), ...photos(2, "after"), ...photos(2, "team")];
    const items = gallery(generateSiteConfig(handmade, mixed));

    expect(new Set(items.map((i) => i.category))).toEqual(new Set(["Antes", "Después", "Equipo"]));
    for (const item of items) expect(item.title).toBeUndefined();
  });

  it("keeps real alt text; otherwise the deterministic business/photo fallback (never the filename)", () => {
    const assets: BusinessAssetInput[] = [
      ...photos(1),
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/IMG_1234.jpg", alt_text: "Muñeco de ganchillo azul" },
      { kind: "image", category: "gallery", origin: "uploaded", storage_url: "https://cdn.example.com/IMG_5678.jpg", alt_text: null },
    ];
    const alts = gallery(generateSiteConfig(handmade, assets)).map((i) => (i.image as { alt: string }).alt);

    expect(alts).toEqual(["Muñeco de ganchillo azul", "Taller Ovillo — foto 2"]);
    expect(alts.join(" ")).not.toMatch(/IMG_/);
  });
});

describe("fact preservation", () => {
  it("only moves or omits existing text — no fact changes and no new sentence appears", () => {
    const site = generateSiteConfig(handmade, photos(12), NEW_DIRECTION);
    const profile = handmade.business_profile;

    expect(site.brand.name).toBe(profile.name);
    const services = blocks(site).find((b) => b.type === "services")!.content as { items: { title: string; description: string }[] };
    expect(services.items.map((s) => [s.title, s.description])).toEqual(profile.services!.map((s) => [s.name, s.description]));
    const contact = JSON.stringify(blocks(site).find((b) => b.type === "contact"));
    for (const fact of [profile.contact!.phone!, profile.contact!.email!, "34600111222"]) expect(contact).toContain(fact);
    for (const src of gallery(site).map((i) => (i.image as { src: string }).src)) {
      expect(photos(12).some((p) => p.storage_url === src)).toBe(true);
    }

    // Every sentence shown in the hero or About is a sentence of the source.
    const sourceSentences = new Set(LONG_DESCRIPTION.split(/(?<=[.!?])\s+/));
    const shown = [hero(site).subheading, about(site)?.subheading].filter(Boolean).join(" ");
    for (const sentence of shown.split(/(?<=[.!?])\s+/)) expect(sourceSentences.has(sentence)).toBe(true);
  });
});
