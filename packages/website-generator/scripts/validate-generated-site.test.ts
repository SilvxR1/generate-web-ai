// Proves the full pipeline the phase asked for:
//   BusinessConfig (real fixture) -> generateSiteConfig -> SiteConfig
//   -> the *existing* renderer/blocks -> a real Astro render.
//
// "Real" here means Astro's own Container API (experimental_AstroContainer)
// actually compiling and rendering PageRenderer.astro with the generated
// page — not just a structural/type check. This is the officially
// documented way to render a real .astro component outside a full
// `astro build` without spinning up a throwaway app; see this package's
// README for why that's the chosen bar of proof.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { experimental_AstroContainer as AstroContainer } from "astro/container";
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { PageRenderer } from "@generate-web-ai/renderer";
import { assertKnownBlockType, BLOCK_TYPES, type BlockConfig } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import { generateSiteConfig } from "../src/generateSiteConfig.ts";

const contactComponentPath = fileURLToPath(
  new URL("../../blocks/src/components/Contact.astro", import.meta.url),
);

describe("generateSiteConfig(reforma valencia fixture)", () => {
  const siteConfig = generateSiteConfig(exampleReformaValenciaConfig);
  const page = siteConfig.pages[0]!;

  it("produces a SiteConfig with only known, renderable block types", () => {
    for (const block of page.blocks) {
      expect(() => assertKnownBlockType(block)).not.toThrow();
    }
    // Sanity: every generated type is actually one BLOCK_TYPES knows —
    // redundant with assertKnownBlockType above, but pins the exact set.
    const generatedTypes = new Set(page.blocks.map((b) => b.type));
    for (const type of generatedTypes) {
      expect(BLOCK_TYPES as readonly string[]).toContain(type);
    }
  });

  it("generates the expected blocks for a fully-populated business", () => {
    const types = page.blocks.map((b) => b.type);
    // hero always present; services/about/cta/contact present because the
    // fixture has services, service_area, and an enabled lead form.
    expect(types).toEqual(["hero", "services", "features", "cta", "contact"]);
  });

  it("derives real business facts, not placeholders", () => {
    expect(siteConfig.brand.name).toBe("Reforma Casa Valencia");

    const hero = page.blocks.find((b) => b.type === "hero");
    expect(hero?.content.heading).toBe("Reforma Casa Valencia");
    expect(hero?.content.eyebrow).toBe("Valencia");

    const services = page.blocks.find((b) => b.type === "services");
    const serviceTitles = services?.content.items.map((item: { title: string }) => item.title) ?? [];
    expect(serviceTitles).toContain("Reforma integral");
    expect(serviceTitles).toContain("Cocinas");

    const contact = page.blocks.find((b) => b.type === "contact");
    expect(contact?.content.details?.some((d: { value: string }) => d.value.includes("960"))).toBe(true);
  });

  it("never invents testimonials, ratings, certifications, or a years-of-experience stat", () => {
    const hero = page.blocks.find((b) => b.type === "hero");
    expect(hero?.content.stat).toBeUndefined();

    const generatedTypes = page.blocks.map((b) => b.type);
    expect(generatedTypes).not.toContain("testimonials");
    expect(generatedTypes).not.toContain("gallery");
  });

  it("builds a lead-capture form with no action (neutral, not wired to any backend)", () => {
    const contact = page.blocks.find((b) => b.type === "contact");
    expect(contact?.content.form).toBeDefined();
    expect(contact?.content.form?.action).toBeUndefined();
    expect(contact?.content.form?.fields.map((f: { name: string }) => f.name)).toEqual(["name", "phone", "service"]);
  });

  it("renders through the real, existing renderer via Astro's Container API", async () => {
    const container = await AstroContainer.create();
    const html = await container.renderToString(PageRenderer, { props: { page } });

    expect(html).toContain("Reforma Casa Valencia");
    expect(html).toContain("Cocinas");
    expect(html).toContain("¿Listo para empezar tu proyecto?");
    // The Contact block's <form> has no `action` (see the earlier
    // "no action" test) — the real, rendered markup must reflect that,
    // which is what makes Contact.astro's client-side handler treat it
    // as not-yet-wired-to-a-backend and dispatch `lead.submitted`
    // instead of letting the browser POST nowhere useful.
    expect(html).toMatch(/<form class="block-contact__form" data-gwa-lead-form method="post"(?! action=)[^>]*>/);
    // Astro's SSR string output references the block's <script> by URL
    // rather than inlining it (that's real Astro build behavior, not a
    // gap) — so the event name is verified directly in the component
    // source that produced this render, not in the SSR HTML string.
    const contactSource = readFileSync(contactComponentPath, "utf-8");
    expect(contactSource).toContain('"lead.submitted"');
  });

  it("produces a valid SiteConfig for a minimal BusinessConfig too (no brand, no services, no contact)", async () => {
    const minimal = generateSiteConfig({
      business_profile: { name: "Taller Genérico", slug: "taller-generico", industry: "other" },
    });

    expect(minimal.pages[0]!.blocks.map((b: BlockConfig) => b.type)).toEqual(["hero", "cta"]);
    expect(minimal.theme.colors.primary).toBeTruthy(); // falls back to the generic default theme
    expect(minimal.business).toBeUndefined(); // no contact facts to report

    const container = await AstroContainer.create();
    const html = await container.renderToString(PageRenderer, { props: { page: minimal.pages[0]! } });
    expect(html).toContain("Taller Genérico");
  });

  it("throws a clear error for an unrecognized required_fields entry, instead of silently dropping it", () => {
    expect(() =>
      generateSiteConfig({
        business_profile: { name: "X", slug: "x", industry: "other" },
        lead_management: { enabled: true, sources: ["website_form"], required_fields: ["not_a_real_field"] },
      }),
    ).toThrow(/Unknown lead_management.required_fields entry/);
  });
});
