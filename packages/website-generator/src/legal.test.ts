import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { LegalTextBlockContent } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
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

function legalTextOf(pages: ReturnType<typeof generateSiteConfig>["pages"], path: string): LegalTextBlockContent {
  const page = pages.find((candidate) => candidate.path === path);
  if (!page) throw new Error(`No page at ${path}`);
  const block = page.blocks[0];
  if (!block) throw new Error(`Page at ${path} has no blocks`);
  if (block.type !== "legal_text") throw new Error(`Expected a legal_text block at ${path}, got ${block.type}`);
  return block.content;
}

describe("generateSiteConfig — legal pages", () => {
  it("always adds /privacy, /terms, and /cookies alongside the homepage", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    expect(site.pages.map((page) => page.path)).toEqual(["/", "/privacy", "/terms", "/cookies"]);
  });

  it("every legal page carries the same non-empty, always-visible disclaimer", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    const disclaimers = ["/privacy", "/terms", "/cookies"].map((path) => legalTextOf(site.pages, path).disclaimer);
    expect(disclaimers.every((text) => text.length > 0)).toBe(true);
    expect(new Set(disclaimers).size).toBe(1);
    expect(disclaimers[0]).toMatch(/not legal advice/i);
    expect(disclaimers[0]).toMatch(/not been reviewed by a lawyer/i);
  });

  it("with no legal_profile, missing facts are surfaced as 'Not provided.', never fabricated", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    const privacy = legalTextOf(site.pages, "/privacy");
    const whoWeAre = privacy.sections.find((section) => section.heading === "Who we are")!;
    expect(whoWeAre.body).toContain("Taller Martinez operates this website.");
    expect(whoWeAre.body).toContain("Registered address: Not provided.");
    expect(whoWeAre.body).toContain("Registration number: Not provided.");
    expect(whoWeAre.body).toContain("Tax ID: Not provided.");

    const processors = privacy.sections.find((section) => section.heading === "Third parties we work with")!;
    expect(processors.body).toBe("No third-party data processors have been listed for this business.");
  });

  it("a filled-in legal_profile's real facts flow through untouched", () => {
    const site = generateSiteConfig(
      minimalBusinessConfig({
        legal_profile: {
          legal_name: "Taller Martinez S.L.",
          registration_number: "B-12345678",
          tax_id: "ESB12345678",
          address: {
            street_address: "Calle Mayor 1",
            locality: "Valencia",
            region: "Valencia",
            postal_code: "46001",
            country: "ES",
          },
          privacy_contact_email: "privacidad@tallermartinez.example",
          data_processors: ["Resend (transactional email)", "Cloudflare (hosting)"],
        },
      }),
    );

    const privacy = legalTextOf(site.pages, "/privacy");
    const whoWeAre = privacy.sections.find((section) => section.heading === "Who we are")!;
    expect(whoWeAre.body).toContain("Taller Martinez S.L. operates this website.");
    expect(whoWeAre.body).toContain("Registered address: Calle Mayor 1, Valencia, Valencia, 46001, ES");
    expect(whoWeAre.body).toContain("Registration number: B-12345678");
    expect(whoWeAre.body).toContain("Tax ID: ESB12345678");
    expect(whoWeAre.body).toContain("Contact for privacy questions: privacidad@tallermartinez.example");

    const processors = privacy.sections.find((section) => section.heading === "Third parties we work with")!;
    expect(processors.body).toBe("Resend (transactional email), Cloudflare (hosting)");

    const terms = legalTextOf(site.pages, "/terms");
    expect(terms.sections[0]?.body).toContain("Taller Martinez S.L.");
  });

  it("the cookie policy is honest about which categories are actually active — none, today", () => {
    const site = generateSiteConfig(minimalBusinessConfig());

    const cookies = legalTextOf(site.pages, "/cookies");
    const howWeUse = cookies.sections.find((section) => section.heading === "How this site uses cookies")!;
    expect(howWeUse.body).toContain("only sets cookies in the Necessary category");
    expect(howWeUse.body).toContain("consent is never assumed or pre-selected");
  });

  it("the privacy page's data-collection section reflects whether a contact form actually exists", () => {
    const withoutForm = legalTextOf(generateSiteConfig(minimalBusinessConfig()).pages, "/privacy");
    const infoWithoutForm = withoutForm.sections.find((section) => section.heading === "Information we collect")!;
    expect(infoWithoutForm.body).toMatch(/does not currently include a contact form/);

    const withForm = legalTextOf(
      generateSiteConfig(
        minimalBusinessConfig({
          lead_management: { enabled: true, sources: ["website_form"] },
        }),
      ).pages,
      "/privacy",
    );
    const infoWithForm = withForm.sections.find((section) => section.heading === "Information we collect")!;
    expect(infoWithForm.body).toMatch(/If you submit this site's contact form/);
  });
});
