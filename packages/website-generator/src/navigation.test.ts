// A8.3.3 — header navigation is generated only from sections that render,
// in rendered order, labelled with each section's own heading. Also writes
// the header-case SiteConfigs apps/api's real-build test builds and runs
// PlatformContract over (toMatchFileSnapshot).
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { MovableSection, SiteConfig, WebsiteCreativeDirection } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";
import { buildNavigation } from "./navigation.ts";

function photos(n: number): BusinessAssetInput[] {
  return Array.from({ length: n }, (_, i) => ({
    kind: "image",
    category: "gallery",
    origin: "uploaded",
    storage_url: `https://cdn.example.com/photo-${i}.jpg`,
    alt_text: null,
  }));
}

const logo: BusinessAssetInput = {
  kind: "logo",
  category: "logo",
  origin: "uploaded",
  storage_url: "https://cdn.example.com/logo.png",
  alt_text: "Logo de Taller Ovillo",
};

const full: BusinessConfig = {
  business_profile: {
    industry: "other",
    name: "Taller Ovillo",
    slug: "taller-ovillo",
    description:
      "Taller familiar de piezas de ganchillo hechas a mano en Valencia. Creamos muñecos y decoración infantil por encargo.",
    services: [{ id: "encargos", name: "Encargos personalizados", description: "Piezas únicas bajo pedido." }],
    contact: { phone: "+34 600 111 222", email: "hola@example.com" },
    target_customers: "Familias que buscan regalos hechos a mano.",
  },
  lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
} as BusinessConfig;

// Services only (no description/about facts, no photos) — a much smaller page.
const sparse: BusinessConfig = {
  business_profile: {
    industry: "home_renovation",
    name: "Reformas Sur, Instalaciones y Mantenimiento Integral del Hogar",
    slug: "reformas-sur",
    services: [{ id: "banos", name: "Reforma de baños", description: "Baños completos." }],
    contact: { phone: "+34 600 333 444" },
  },
  lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
} as BusinessConfig;

const direction = (sectionOrder: MovableSection[]): WebsiteCreativeDirection => ({
  version: "1",
  strategy: "new_direction",
  family: "hospitality",
  palette: { mode: "family" },
  typography: { pairing: "classic_serif" },
  radius: "soft",
  density: "compact",
  sectionOrder,
  hero: { layout: "centered" },
  gallery: { maxItems: 6, layout: "grid" },
  surfaces: { mode: "flat" },
  cta: { variant: "emphasis" },
  rationale: "A distinctly different presentation.",
});

function renderedIds(site: SiteConfig): string[] {
  return site.pages[0]!.blocks.map((b) => b.id).filter((id): id is string => Boolean(id));
}

describe("buildNavigation", () => {
  it("links every navigable rendered section, in page order, labelled with its own heading", () => {
    const site = generateSiteConfig(full, [logo, ...photos(8)]);

    expect(site.navigation).toEqual([
      { label: "Nuestras creaciones", href: "#gallery" },
      { label: "Lo que hacemos", href: "#services" },
      { label: "Nuestra historia", href: "#about" },
      { label: "Hablemos", href: "#contact" },
    ]);
  });

  it("every generated href resolves to a rendered section id (the PlatformContract invariant)", () => {
    for (const [config, assets] of [
      [full, [logo, ...photos(8)]],
      [sparse, []],
    ] as const) {
      const site = generateSiteConfig(config, assets);
      const ids = new Set(renderedIds(site));
      for (const item of site.navigation ?? []) expect(ids.has(item.href.slice(1))).toBe(true);
    }
  });

  it("a section that doesn't render gets no link, and none is invented for it", () => {
    const site = generateSiteConfig(sparse, []);

    expect(renderedIds(site)).toEqual(["hero", "services", "cta", "contact"]);
    expect(site.navigation?.map((n) => n.href)).toEqual(["#services", "#contact"]);
  });

  it("follows a direction's reordered sections", () => {
    const site = generateSiteConfig(full, [logo, ...photos(8)], direction(["about", "services", "gallery"]));

    expect(site.navigation?.map((n) => n.href)).toEqual(["#about", "#services", "#gallery", "#contact"]);
  });

  it("never lists the hero or the CTA, and contact is always last when present", () => {
    const hrefs = generateSiteConfig(full, photos(3)).navigation!.map((n) => n.href);

    expect(hrefs).not.toContain("#hero");
    expect(hrefs).not.toContain("#cta");
    expect(hrefs.at(-1)).toBe("#contact");
  });

  it("is omitted entirely when nothing is worth linking", () => {
    const bare = { business_profile: { industry: "other", name: "Taller", slug: "taller" } } as BusinessConfig;
    expect(generateSiteConfig(bare, []).navigation).toBeUndefined();
  });

  it("labels are the page's existing section headings — no new marketing copy", () => {
    const site = generateSiteConfig(full, photos(3));
    const headings = new Set(site.pages[0]!.blocks.map((b) => (b.content as { heading?: string }).heading));
    for (const item of site.navigation!) expect(headings.has(item.label)).toBe(true);
  });

  it("skips blocks without an id or a heading", () => {
    expect(
      buildNavigation([
        { type: "services", content: { heading: "Servicios", items: [] } },
        { type: "gallery", id: "gallery", content: { items: [] } },
      ]),
    ).toEqual([]);
  });
});

describe("header-case SiteConfig fixtures for the backend real-build test", () => {
  it("are up to date with the generator", async () => {
    const output = {
      full_with_logo: generateSiteConfig(full, [logo, ...photos(8)]),
      no_logo_missing_sections_long_name: generateSiteConfig(sparse, []),
      reordered_new_direction: generateSiteConfig(full, [logo, ...photos(8)], direction(["about", "services", "gallery"])),
    };
    await expect(`${JSON.stringify(output, null, 2)}\n`).toMatchFileSnapshot("../../../apps/api/tests/fixtures/a8_header_site_configs.json");
  });
});
