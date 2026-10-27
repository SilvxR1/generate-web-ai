// C2.1 — contact form (message, consent, first-layer notice) and accent contrast.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { ContactBlockContent } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import { generateSiteConfig } from "./generateSiteConfig.ts";
import { accessibleAccent, contrastRatio } from "./palette.ts";

function config(overrides: Partial<BusinessConfig> = {}): BusinessConfig {
  return {
    business_profile: { industry: "other", name: "Taller Martinez", slug: "taller-martinez" },
    lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
    ...overrides,
  };
}

function contactForm(site: ReturnType<typeof generateSiteConfig>) {
  const block = site.pages[0]!.blocks.find((candidate) => candidate.type === "contact");
  if (!block || block.type !== "contact") throw new Error("no contact block");
  const form = (block.content as ContactBlockContent).form;
  if (!form) throw new Error("no form");
  return form;
}

describe("contact form (C2.1)", () => {
  it("always offers a message field, optional unless the business requires it", () => {
    const optional = contactForm(generateSiteConfig(config())).fields.find((field) => field.name === "message");
    expect(optional).toMatchObject({ type: "textarea", required: false });

    const required = contactForm(
      generateSiteConfig(
        config({ lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "message"] } }),
      ),
    ).fields.filter((field) => field.name === "message");
    expect(required).toHaveLength(1);
    expect(required[0]).toMatchObject({ required: true });
  });

  it("adds a required consent checkbox only when consent_required is set", () => {
    expect(contactForm(generateSiteConfig(config())).fields.some((field) => field.name === "consent")).toBe(false);

    const form = contactForm(
      generateSiteConfig(
        config({ lead_management: { enabled: true, sources: ["website_form"], consent_required: true } }),
      ),
    );
    const consent = form.fields.find((field) => field.name === "consent");
    expect(consent).toMatchObject({ type: "checkbox", required: true });
    expect(form.privacyNotice?.text).toContain("Legitimación: tu consentimiento.");
  });

  it("shows a first-layer privacy notice linking to the privacy policy, never inventing the holder", () => {
    const notice = contactForm(generateSiteConfig(config())).privacyNotice!;
    expect(notice.href).toBe("/privacidad");
    expect(notice.text).toContain("Responsable: pendiente de completar por el titular.");
    expect(notice.text).not.toContain("Taller Martinez");

    const named = contactForm(generateSiteConfig(config({ legal_profile: { legal_name: "Ana Pérez García" } })));
    expect(named.privacyNotice!.text).toContain("Responsable: Ana Pérez García.");
  });

  it("uses the owner's own first-layer notice verbatim when provided", () => {
    const form = contactForm(generateSiteConfig(config({ legal_profile: { first_layer_notice: "Texto del titular." } })));
    expect(form.privacyNotice!.text).toBe("Texto del titular.");
  });
});

describe("accessibleAccent (C2.1)", () => {
  it("darkens a failing hex accent until it passes AA as text and behind white text", () => {
    const accent = accessibleAccent("#ea580c", "#fffbf5");
    expect(accent).not.toBe("#ea580c");
    expect(contrastRatio(accent, "#fffbf5")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(accent, "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps a passing or non-hex accent unchanged", () => {
    expect(accessibleAccent("#1e3a8a", "#ffffff")).toBe("#1e3a8a");
    expect(accessibleAccent("var(--brand)", "#ffffff")).toBe("var(--brand)");
  });

  it("every generated theme's accent passes", () => {
    const site = generateSiteConfig(config());
    const { accent, background } = site.theme.colors;
    expect(contrastRatio(accent, background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(accent, "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
});
