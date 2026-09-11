// Regression coverage for the empty/missing SEO description bug: a
// BusinessConfig with no explicit website.seo.description (or an
// explicitly blank one) must still produce a non-empty
// SiteConfig.seo.description, via a deterministic name/location-based
// fallback — never AI-generated copy.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";

function minimalBusinessConfig(overrides: Partial<BusinessConfig> = {}): BusinessConfig {
  return {
    business_profile: {
      industry: "other",
      name: "Taller Martinez",
      slug: "taller-martinez",
    },
    ...overrides,
  };
}

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

describe("generateSiteConfig — seo.description fallback", () => {
  it("is non-empty for a minimal BusinessConfig with no description, no location, and no website.seo", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    expect(site.seo.description).toBe("Taller Martinez — servicios profesionales");
  });

  it("uses the business description when present", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: "Reparación de vehículos con más de una ubicación.",
        },
      }),
    );

    expect(site.seo.description).toBe("Reparación de vehículos con más de una ubicación.");
  });

  it("falls back to name + location when description is absent but location exists", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          location: { city: "Valencia", country: "ES" },
        },
      }),
    );

    expect(site.seo.description).toBe("Taller Martinez — servicios profesionales en Valencia");
  });

  it("falls through to the deterministic fallback when website.seo.description is an empty string", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        website: { seo: { description: "" } },
      }),
    );

    expect(site.seo.description).toBe("Taller Martinez — servicios profesionales");
  });

  it("falls through to the deterministic fallback when business description is whitespace-only", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: "   ",
        },
      }),
    );

    expect(site.seo.description).toBe("Taller Martinez — servicios profesionales");
  });

  it("prefers an explicit non-blank website.seo.description over the business description", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: "Business description",
        },
        website: { seo: { description: "Custom SEO copy" } },
      }),
    );

    expect(site.seo.description).toBe("Custom SEO copy");
  });
});

// Regression coverage for the publish-time 422 bug: BusinessProfile.description
// (apps/api's app.domain.business_config.business_profile) allows up to
// 2000 chars, but the backend's SiteSEOPayload.description /
// SEOPreferences.description (app.schemas.site_config /
// app.domain.business_config.website) both cap at 500 — a business
// whose real description ran past 500 chars used to fail
// POST .../website/publish with a 422 "Request validation failed"
// every time, since nothing here ever shortened it first.
describe("generateSiteConfig — seo.description length cap", () => {
  it("truncates a business description longer than 500 chars to fit the backend's limit", () => {
    const longDescription = "Reforma integral de cocinas y baños en Valencia. ".repeat(20); // 1000 chars
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: longDescription,
        },
      }),
    );

    expect(site.seo.description.length).toBeLessThanOrEqual(500);
    expect(longDescription.length).toBeGreaterThan(500); // sanity: the input really was too long
  });

  it("truncates at a word boundary rather than mid-word, and marks the cut with an ellipsis", () => {
    const longDescription = "Reforma integral de cocinas y baños en Valencia. ".repeat(20);
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: longDescription,
        },
      }),
    );

    expect(site.seo.description.endsWith("…")).toBe(true);
    expect(site.seo.description.at(-2)).not.toBe(" ");
    // Never chopped a word in half: everything before the ellipsis is a
    // prefix of the real, original description.
    const withoutEllipsis = site.seo.description.slice(0, -1);
    expect(longDescription.startsWith(withoutEllipsis)).toBe(true);
  });

  it("leaves a description already within the limit untouched", () => {
    const shortDescription = "Reparación de vehículos con más de una ubicación.";
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Taller Martinez",
          slug: "taller-martinez",
          description: shortDescription,
        },
      }),
    );

    expect(site.seo.description).toBe(shortDescription);
  });

  it("also caps an over-long explicit website.seo.description the same way", () => {
    const longDescription = "Custom SEO copy for a very detailed landing page. ".repeat(20);
    const site = generateSiteConfig(
      minimalBusinessConfig({
        website: { seo: { description: longDescription } },
      }),
    );

    expect(site.seo.description.length).toBeLessThanOrEqual(500);
  });
});

// P1.1: WhatsApp CTA generation — never fabricated, never forced on,
// placements strictly follow configuration.
describe("generateSiteConfig — WhatsApp", () => {
  it("omits site.whatsapp entirely when not configured", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    expect(site.whatsapp).toBeUndefined();
  });

  it("omits site.whatsapp when whatsapp is present but disabled", () => {
    const site = generateSiteConfig(minimalBusinessConfig({ whatsapp: { enabled: false } }));

    expect(site.whatsapp).toBeUndefined();
  });

  it("maps a fully-configured whatsapp block to site-config's camelCase shape", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        whatsapp: {
          enabled: true,
          phone_number: "+34 600 123 456",
          default_message: "Hola, he visto vuestra web y me gustaría solicitar información.",
          show_floating_button: true,
          show_contact_cta: true,
          tracking_enabled: true,
        },
      }),
    );

    expect(site.whatsapp).toEqual({
      enabled: true,
      phoneNumber: "+34 600 123 456",
      defaultMessage: "Hola, he visto vuestra web y me gustaría solicitar información.",
      showFloatingButton: true,
      showContactCta: true,
      trackingEnabled: true,
    });
  });

  it("never renders a contact-section WhatsApp CTA when show_contact_cta is false", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        whatsapp: { enabled: true, phone_number: "+34600123456", show_contact_cta: false },
      }),
    );

    const contact = site.pages[0]?.blocks.find((b) => b.type === "contact");
    expect(contact).toBeUndefined(); // no other contact detail configured either
  });

  it("renders a contact-section WhatsApp CTA with a wa.me link and prefilled message when show_contact_cta is true", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        whatsapp: {
          enabled: true,
          phone_number: "+34 600 123 456",
          default_message: "Hola!",
          show_contact_cta: true,
        },
      }),
    );

    const contact = site.pages[0]?.blocks.find((b) => b.type === "contact");
    expect(contact).toBeDefined();
    if (contact?.type !== "contact") throw new Error("expected a contact block");
    expect(contact.content.whatsappCta?.href).toBe("https://wa.me/34600123456?text=Hola!");
    expect(contact.content.whatsappCta?.label).toBeTruthy();
  });

  it("never fabricates a phone number — no digits appear that weren't in the real config", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        whatsapp: { enabled: true, phone_number: "+34611222333", show_contact_cta: true },
      }),
    );

    const contact = site.pages[0]?.blocks.find((b) => b.type === "contact");
    if (contact?.type !== "contact") throw new Error("expected a contact block");
    expect(contact.content.whatsappCta?.href).toContain("34611222333");
  });
});

// LR-05: real uploaded assets must reach SiteConfig — logo in brand.logo,
// hero photo in the hero block, remaining photos in a gallery block —
// and a real asset always wins over the text/no-image fallback.
describe("generateSiteConfig — real asset propagation", () => {
  it("uses a real uploaded logo in brand.logo", () => {
    const logo = asset({ kind: "logo", category: "logo", storage_url: "https://api.example.com/uploads/biz/logo.png" });
    const site = generateSiteConfig(minimalBusinessConfig(), [logo]);

    expect(site.brand.logo).toEqual({ src: logo.storage_url, alt: expect.stringContaining("Taller Martinez") });
  });

  it("falls back to text (no logo) when no real logo asset exists", () => {
    const site = generateSiteConfig(minimalBusinessConfig(), [asset({ category: "gallery" })]);
    expect(site.brand.logo).toBeUndefined();
    expect(site.brand.name).toBe("Taller Martinez");
  });

  it("a real uploaded logo takes priority over a manually-entered brand.logo", () => {
    const realLogo = asset({ kind: "logo", storage_url: "https://api.example.com/uploads/biz/real-logo.png" });
    const site = generateSiteConfig(
      minimalBusinessConfig({
        brand: {
          colors: { primary: "#000", secondary: "#111", accent: "#222", background: "#fff", foreground: "#000" },
          typography: { sans: "Inter, sans-serif" },
          logo: { url: "https://elsewhere.example.com/manual-logo.png", alt: "Manual logo" },
        },
      }),
      [realLogo],
    );

    expect(site.brand.logo?.src).toBe(realLogo.storage_url);
  });

  it("uses the manually-entered brand.logo when no real BusinessAsset logo exists", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        brand: {
          colors: { primary: "#000", secondary: "#111", accent: "#222", background: "#fff", foreground: "#000" },
          typography: { sans: "Inter, sans-serif" },
          logo: { url: "https://elsewhere.example.com/manual-logo.png", alt: "Manual logo" },
        },
      }),
      [],
    );

    expect(site.brand.logo).toEqual({ src: "https://elsewhere.example.com/manual-logo.png", alt: "Manual logo" });
  });

  it("uses a real gallery/product photo as the hero image", () => {
    const photo = asset({ category: "hero_candidate", storage_url: "https://api.example.com/uploads/biz/hero.jpg" });
    const site = generateSiteConfig(minimalBusinessConfig(), [photo]);

    const hero = site.pages[0]?.blocks.find((b) => b.type === "hero");
    if (hero?.type !== "hero") throw new Error("expected a hero block");
    expect(hero.content.image?.src).toBe(photo.storage_url);
  });

  it("renders no hero image when there are no real photos", () => {
    const site = generateSiteConfig(minimalBusinessConfig(), []);
    const hero = site.pages[0]?.blocks.find((b) => b.type === "hero");
    if (hero?.type !== "hero") throw new Error("expected a hero block");
    expect(hero.content.image).toBeUndefined();
  });

  it("builds a gallery block from real product/project photos, excluding whichever one became the hero image", () => {
    const hero = asset({ category: "hero_candidate", storage_url: "https://api.example.com/uploads/biz/hero.jpg" });
    const photos = [
      asset({ category: "product", storage_url: "https://api.example.com/uploads/biz/p1.jpg" }),
      asset({ category: "product", storage_url: "https://api.example.com/uploads/biz/p2.jpg" }),
    ];
    const site = generateSiteConfig(minimalBusinessConfig(), [hero, ...photos]);

    const gallery = site.pages[0]?.blocks.find((b) => b.type === "gallery");
    expect(gallery).toBeDefined();
    if (gallery?.type !== "gallery") throw new Error("expected a gallery block");
    expect(gallery.content.items).toHaveLength(2);
    expect(gallery.content.items.map((item) => item.image.src)).toEqual(photos.map((p) => p.storage_url));
  });

  it("omits the gallery block entirely when there are no real gallery-worthy photos", () => {
    const site = generateSiteConfig(minimalBusinessConfig(), []);
    expect(site.pages[0]?.blocks.some((b) => b.type === "gallery")).toBe(false);
  });

  it("never shows the same photo as both the hero image and a gallery item", () => {
    const photo = asset({ category: "hero_candidate", storage_url: "https://api.example.com/uploads/biz/hero.jpg" });
    const other = asset({ category: "product", storage_url: "https://api.example.com/uploads/biz/other.jpg" });
    const site = generateSiteConfig(minimalBusinessConfig(), [photo, other]);

    const gallery = site.pages[0]?.blocks.find((b) => b.type === "gallery");
    if (gallery?.type !== "gallery") throw new Error("expected a gallery block");
    expect(gallery.content.items.some((item) => item.image.src === photo.storage_url)).toBe(false);
  });

  it("ignores low_quality assets for every role", () => {
    const bad = asset({ kind: "logo", category: "low_quality", storage_url: "https://api.example.com/uploads/biz/bad.png" });
    const site = generateSiteConfig(minimalBusinessConfig(), [bad]);
    expect(site.brand.logo).toBeUndefined();
  });
});

// LR-08: internal briefing/strategy commentary in BusinessProfile.description
// must never surface as hero copy, about copy, or SEO description.
describe("generateSiteConfig — business-brief vs customer-facing copy", () => {
  it("never publishes 'the business currently has no website' as hero or SEO copy", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Cositas y Puntos",
          slug: "cositas-y-puntos",
          description:
            "Amigurumis hechos a mano en Valencia. The business currently has no website yet, its main presence is Instagram.",
        },
      }),
    );

    const hero = site.pages[0]?.blocks.find((b) => b.type === "hero");
    if (hero?.type !== "hero") throw new Error("expected a hero block");
    expect(hero.content.subheading).not.toMatch(/no website/i);
    expect(hero.content.subheading).not.toMatch(/instagram/i);
    expect(site.seo.description).not.toMatch(/no website/i);
  });

  it("never publishes a 'no ecommerce/cart/payment in this first version' scoping note", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Cositas y Puntos",
          slug: "cositas-y-puntos",
          description: "Piezas de crochet artesanales. No ecommerce/cart/payment in this first version.",
        },
      }),
    );

    const hero = site.pages[0]?.blocks.find((b) => b.type === "hero");
    if (hero?.type !== "hero") throw new Error("expected a hero block");
    expect(hero.content.subheading).not.toMatch(/ecommerce/i);
    expect(hero.content.subheading).not.toMatch(/first version/i);
  });

  it("still publishes the real, customer-facing part of the description", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        business_profile: {
          industry: "other",
          name: "Cositas y Puntos",
          slug: "cositas-y-puntos",
          description: "Amigurumis hechos a mano en Valencia. The business currently has no website yet.",
        },
      }),
    );

    const hero = site.pages[0]?.blocks.find((b) => b.type === "hero");
    if (hero?.type !== "hero") throw new Error("expected a hero block");
    expect(hero.content.subheading).toContain("Amigurumis hechos a mano en Valencia.");
  });
});

// LR-07: unrelated businesses must be visually/configurationally
// distinct — not just different text on the same template.
describe("generateSiteConfig — creative diversity across business families", () => {
  // No `brand` at all — the real "first real customer" scenario: no
  // previous website, no existing color system. Several real product
  // photos are the only signal available, which is exactly the case
  // LR-07 requires this generator to use.
  const artisanConfig: BusinessConfig = {
    business_profile: {
      industry: "other",
      name: "Cositas y Puntos",
      slug: "cositas-y-puntos",
      description: "Amigurumis y piezas de crochet hechas a mano.",
      location: { city: "Valencia", country: "ES" },
    },
  };
  const artisanPhotos: BusinessAssetInput[] = [
    asset({ category: "product", storage_url: "https://api.example.com/uploads/biz/amigurumi-1.jpg" }),
    asset({ category: "product", storage_url: "https://api.example.com/uploads/biz/amigurumi-2.jpg" }),
  ];

  const renovationConfig: BusinessConfig = {
    business_profile: {
      industry: "home_renovation",
      name: "Reformas Valencia",
      slug: "reformas-valencia",
      description: "Reformas integrales de cocinas y baños.",
      location: { city: "Valencia", country: "ES" },
    },
  };

  const professionalConfig: BusinessConfig = {
    business_profile: {
      industry: "b2b_services",
      name: "Asesoría Martín",
      slug: "asesoria-martin",
      description: "Asesoría fiscal y contable para pequeñas empresas.",
    },
  };

  it("gives an artisan business a different theme than a renovation business", () => {
    const artisanSite = generateSiteConfig(artisanConfig, artisanPhotos);
    const renovationSite = generateSiteConfig(renovationConfig);

    expect(artisanSite.theme.colors).not.toEqual(renovationSite.theme.colors);
    expect(artisanSite.theme.radius).not.toEqual(renovationSite.theme.radius);
  });

  it("gives three unrelated businesses three distinct theme palettes", () => {
    const artisanSite = generateSiteConfig(artisanConfig, artisanPhotos);
    const renovationSite = generateSiteConfig(renovationConfig);
    const professionalSite = generateSiteConfig(professionalConfig);

    const palettes = [artisanSite.theme.colors, renovationSite.theme.colors, professionalSite.theme.colors];
    const unique = new Set(palettes.map((p) => JSON.stringify(p)));
    expect(unique.size).toBe(3);
  });

  it("gives a renovation business a stronger CTA than a professional-services business", () => {
    const renovationSite = generateSiteConfig(renovationConfig);
    const professionalSite = generateSiteConfig(professionalConfig);

    const renovationCta = renovationSite.pages[0]?.blocks.find((b) => b.type === "cta");
    const professionalCta = professionalSite.pages[0]?.blocks.find((b) => b.type === "cta");
    if (renovationCta?.type !== "cta" || professionalCta?.type !== "cta") throw new Error("expected cta blocks");

    expect(renovationCta.content.variant).toBe("emphasis");
    expect(professionalCta.content.variant).toBeUndefined();
  });

  it("is deterministic: the same BusinessConfig always produces the same theme", () => {
    const first = generateSiteConfig(renovationConfig);
    const second = generateSiteConfig(renovationConfig);
    expect(first.theme).toEqual(second.theme);
  });

  it("is deterministic for asset-driven family resolution too", () => {
    const first = generateSiteConfig(artisanConfig, artisanPhotos);
    const second = generateSiteConfig(artisanConfig, artisanPhotos);
    expect(first.theme).toEqual(second.theme);
  });

  it("places a renovation business's real project photos after its services, not right after the hero", () => {
    const photos = [
      asset({ category: "hero_candidate", storage_url: "https://api.example.com/uploads/biz/hero.jpg" }),
      asset({ category: "project", storage_url: "https://api.example.com/uploads/biz/project.jpg" }),
    ];
    const site = generateSiteConfig(renovationConfig, photos);
    const order = site.pages[0]?.blocks.map((b) => b.type) ?? [];
    expect(order.indexOf("gallery")).toBeGreaterThan(order.indexOf("services"));
  });

  it("places an artisan business's real product photos right after the hero", () => {
    const site = generateSiteConfig(artisanConfig, artisanPhotos);
    const order = site.pages[0]?.blocks.map((b) => b.type) ?? [];
    expect(order.indexOf("gallery")).toBe(1);
  });

  it("a renovation business's own visual_style keywords never flip it into the artisan family", () => {
    // Regression: the reforma-valencia fixture's real visual_style is
    // "warm, mediterranean, editorial" — this must stay construction.
    const site = generateSiteConfig({
      ...renovationConfig,
      brand: {
        colors: { primary: "#111", secondary: "#222", accent: "#333", background: "#fff", foreground: "#000" },
        typography: { sans: "Inter, sans-serif" },
        visual_style: "warm, mediterranean, editorial",
      },
    });
    const cta = site.pages[0]?.blocks.find((b) => b.type === "cta");
    if (cta?.type !== "cta") throw new Error("expected a cta block");
    expect(cta.content.variant).toBe("emphasis"); // construction family, not artisan
  });
});
