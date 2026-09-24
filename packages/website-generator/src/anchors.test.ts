// A8.1.2 — the generated-SiteConfig anchor invariant: every in-page
// href="#X" a generated page emits must target a block on that same page
// whose `id` is X (and which therefore renders id="X"). The deployed
// PlatformContract (apps/api app.qa.platform_contract,
// broken_anchor_target) rejects any build that breaks this, so the
// generator must satisfy it *before* validation — including for every
// conditional block (contact, services), never by emitting an empty
// placeholder section just to own an id.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import type { SiteConfig } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";

function collectAnchors(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) {
    for (const item of value) collectAnchors(item, found);
  } else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (key === "href" && typeof child === "string" && child.startsWith("#")) found.push(child.slice(1));
      else collectAnchors(child, found);
    }
  }
  return found;
}

/** Every page's dangling in-page anchors, keyed by page path. */
function danglingAnchors(site: SiteConfig): Record<string, string[]> {
  const dangling: Record<string, string[]> = {};
  for (const page of site.pages) {
    const ids = new Set(page.blocks.map((block) => block.id).filter(Boolean));
    const missing = page.blocks.flatMap((block) => collectAnchors(block.content)).filter((target) => !ids.has(target));
    if (missing.length > 0) dangling[page.path] = missing;
  }
  return dangling;
}

const base: BusinessConfig = {
  business_profile: { industry: "other", name: "Taller Martinez", slug: "taller-martinez" },
};

const withServices = {
  business_profile: {
    ...base.business_profile,
    services: [{ id: "s1", name: "Reparación", short_description: "Reparaciones rápidas" }],
  },
} as BusinessConfig;

const withPhone = {
  business_profile: { ...base.business_profile, contact: { phone: "+34 600 000 000" } },
} as BusinessConfig;

const withLeadFormOnly = {
  ...base,
  lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
} as BusinessConfig;

const withWhatsappContactCtaOnly = {
  ...base,
  whatsapp: { enabled: true, phone_number: "+34600123456", show_contact_cta: true },
} as BusinessConfig;

const withWhatsappNoContactCta = {
  ...base,
  whatsapp: { enabled: true, phone_number: "+34600123456", show_contact_cta: false },
} as BusinessConfig;

const photos: BusinessAssetInput[] = [
  {
    kind: "image",
    category: "hero_candidate",
    origin: "uploaded",
    storage_url: "https://api.example.com/uploads/biz/hero.jpg",
    alt_text: null,
  },
  {
    kind: "image",
    category: "gallery",
    origin: "uploaded",
    storage_url: "https://api.example.com/uploads/biz/g.jpg",
    alt_text: null,
  },
];

describe("generateSiteConfig — in-page anchor invariant", () => {
  const cases: [string, BusinessConfig, BusinessAssetInput[]][] = [
    ["minimal (no services, no contact)", base, []],
    ["services only, no contact", withServices, []],
    ["phone only", withPhone, []],
    ["lead form only", withLeadFormOnly, []],
    ["WhatsApp contact CTA only", withWhatsappContactCtaOnly, []],
    ["WhatsApp without contact CTA (no contact section)", withWhatsappNoContactCta, []],
    ["real reforma-valencia fixture", exampleReformaValenciaConfig, []],
    ["real reforma-valencia fixture with photos", exampleReformaValenciaConfig, photos],
  ];

  it.each(cases)("every #anchor resolves to a block id on its page: %s", (_label, config, assets) => {
    expect(danglingAnchors(generateSiteConfig(config, assets))).toEqual({});
  });

  it("emits no #contact anchor at all when there is no contact section", () => {
    const home = generateSiteConfig(withWhatsappNoContactCta).pages[0]!;

    expect(home.blocks.find((block) => block.type === "contact")).toBeUndefined();
    expect(home.blocks.find((block) => block.type === "cta")).toBeUndefined();
    expect(collectAnchors(home.blocks)).not.toContain("contact");
  });

  it("never invents an empty contact section just to satisfy an anchor", () => {
    const home = generateSiteConfig(base).pages[0]!;
    expect(home.blocks.map((block) => block.type)).toEqual(["hero"]);
  });

  it("links the hero and CTA to #contact, and the hero to #services, when those sections exist", () => {
    const home = generateSiteConfig(exampleReformaValenciaConfig).pages[0]!;
    const ids = home.blocks.map((block) => block.id);

    expect(ids).toContain("contact");
    expect(ids).toContain("services");
    const hero = home.blocks.find((block) => block.type === "hero");
    const cta = home.blocks.find((block) => block.type === "cta");
    if (hero?.type !== "hero" || cta?.type !== "cta") throw new Error("expected hero and cta blocks");
    expect(hero.content.primaryAction?.href).toBe("#contact");
    expect(hero.content.secondaryAction?.href).toBe("#services");
    expect(cta.content.primaryAction.href).toBe("#contact");
  });
});
