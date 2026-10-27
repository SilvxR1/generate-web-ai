import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import type { LegalTextBlockContent } from "@generate-web-ai/site-config";
import { describe, expect, it } from "vitest";
import { generateSiteConfig } from "./generateSiteConfig.ts";
import { buildLegalPages } from "./legal.ts";
import { PENDING, spanishLegalPendingFacts } from "./legal-es.ts";

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

// The English templates (locale "en") — no longer what generateSiteConfig
// emits (C2.1: generated sites are Spanish), but still the default of
// buildLegalPages and kept unchanged for any English consumer.
function englishSite(config: BusinessConfig): { pages: ReturnType<typeof buildLegalPages> } {
  const leads = config.lead_management;
  const hasForm = Boolean(leads?.enabled && (leads.sources ?? []).includes("website_form"));
  return { pages: buildLegalPages(config.business_profile, config.legal_profile ?? undefined, hasForm) };
}

function legalTextOf(pages: ReturnType<typeof generateSiteConfig>["pages"], path: string): LegalTextBlockContent {
  const page = pages.find((candidate) => candidate.path === path);
  if (!page) throw new Error(`No page at ${path}`);
  const block = page.blocks[0];
  if (!block) throw new Error(`Page at ${path} has no blocks`);
  if (block.type !== "legal_text") throw new Error(`Expected a legal_text block at ${path}, got ${block.type}`);
  return block.content;
}

describe("buildLegalPages — English templates", () => {
  it("produces /privacy, /terms, and /cookies", () => {
    const site = englishSite(minimalBusinessConfig());

    expect(site.pages.map((page) => page.path)).toEqual(["/privacy", "/terms", "/cookies"]);
  });

  it("every legal page carries the same non-empty, always-visible disclaimer", () => {
    const site = englishSite(minimalBusinessConfig());

    const disclaimers = ["/privacy", "/terms", "/cookies"].map((path) => legalTextOf(site.pages, path).disclaimer ?? "");
    expect(disclaimers.every((text) => text.length > 0)).toBe(true);
    expect(new Set(disclaimers).size).toBe(1);
    expect(disclaimers[0]).toMatch(/not legal advice/i);
    expect(disclaimers[0]).toMatch(/not been reviewed by a lawyer/i);
  });

  it("with no legal_profile, missing facts are surfaced as 'Not provided.', never fabricated", () => {
    const site = englishSite(minimalBusinessConfig());

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
    const site = englishSite(
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
    const site = englishSite(minimalBusinessConfig());

    const cookies = legalTextOf(site.pages, "/cookies");
    const howWeUse = cookies.sections.find((section) => section.heading === "How this site uses cookies")!;
    // P3: the site's own code sets no cookies; only optional, consent-gated analytics exists.
    expect(howWeUse.body).toContain("website code sets no cookies");
    expect(howWeUse.body).toContain("If you accept the Analytics category");
    expect(howWeUse.body).not.toContain("Marketing");
    expect(howWeUse.body).toContain("Consent is never assumed or pre-selected");
  });

  it("the privacy page's data-collection section reflects whether a contact form actually exists", () => {
    const withoutForm = legalTextOf(englishSite(minimalBusinessConfig()).pages, "/privacy");
    const infoWithoutForm = withoutForm.sections.find((section) => section.heading === "Information we collect")!;
    expect(infoWithoutForm.body).toMatch(/does not currently include a contact form/);

    const withForm = legalTextOf(
      englishSite(
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

const FULL_SPANISH_LEGAL = {
  legal_name: "Ana Pérez García",
  tax_id: "12345678Z",
  address: { street_address: "Calle Ejemplo 1", locality: "Valencia", postal_code: "46001", country: "ES" },
  privacy_contact_email: "privacidad@ejemplo.example",
  data_processors: ["Resend (correo)", "Cloudflare (alojamiento)"],
  data_retention: "Hasta 12 meses desde la última comunicación.",
};

function spanishSite(overrides: Partial<BusinessConfig> = {}) {
  return generateSiteConfig(
    minimalBusinessConfig({ lead_management: { enabled: true, sources: ["website_form"] }, ...overrides }),
  );
}

function allLegalText(site: ReturnType<typeof generateSiteConfig>): string {
  return ["/aviso-legal", "/privacidad", "/cookies"]
    .map((path) => {
      const content = legalTextOf(site.pages, path);
      return [content.disclaimer ?? "", ...content.sections.map((section) => `${section.heading} ${section.body}`)].join("\n");
    })
    .join("\n");
}

describe("generateSiteConfig — Spanish legal pages (C2.1)", () => {
  it("emits locale es with Aviso legal, Privacidad and Cookies", () => {
    const site = spanishSite();
    expect(site.locale).toBe("es");
    expect(site.pages.map((page) => page.path)).toEqual(["/", "/aviso-legal", "/privacidad", "/cookies"]);
  });

  it("marks every missing fact as pending and never uses the brand name as the legal holder", () => {
    const site = spanishSite();
    const notice = legalTextOf(site.pages, "/aviso-legal");
    const holder = notice.sections[0]!.body;
    expect(holder).toContain(`Titular: ${PENDING}`);
    expect(holder).toContain(`NIF: ${PENDING}`);
    expect(holder).toContain(`Domicilio: ${PENDING}`);
    expect(holder).not.toContain("Titular: Taller Martinez");
    expect(notice.disclaimer).toMatch(/pendientes de completar/);

    const privacy = legalTextOf(site.pages, "/privacidad");
    expect(privacy.sections.find((section) => section.heading === "Legitimación")!.body).toBe(PENDING);
    expect(privacy.sections.find((section) => section.heading === "Conservación")!.body).toBe(PENDING);
  });

  it("with every fact provided there is no pending marker and no notice; facts flow through verbatim", () => {
    const config = minimalBusinessConfig({
      lead_management: { enabled: true, sources: ["website_form"], consent_required: true },
      legal_profile: FULL_SPANISH_LEGAL,
    });
    const site = generateSiteConfig(config);
    const text = allLegalText(site);
    expect(text).not.toContain(PENDING);
    for (const path of ["/aviso-legal", "/privacidad", "/cookies"]) {
      expect(legalTextOf(site.pages, path).disclaimer).toBeUndefined();
    }
    expect(text).toContain("Titular: Ana Pérez García");
    expect(text).toContain("NIF: 12345678Z");
    expect(text).toContain("Domicilio: Calle Ejemplo 1, 46001, Valencia, ES");
    expect(text).toContain("Hasta 12 meses desde la última comunicación.");
    expect(text).toContain("Resend (correo), Cloudflare (alojamiento)");
    expect(text).toContain("Tu consentimiento");
    expect(
      spanishLegalPendingFacts(config.business_profile, config.legal_profile ?? undefined, {
        hasContactForm: true,
        leadManagement: config.lead_management ?? undefined,
      }),
    ).toEqual([]);
  });

  it("lists the pending facts by stable id (mirrored by the API's publication gate)", () => {
    expect(
      spanishLegalPendingFacts(minimalBusinessConfig().business_profile, undefined, { hasContactForm: true }),
    ).toEqual(["legal_name", "tax_id", "address", "contact_email", "data_retention", "legal_basis"]);
    // Without a form there is no retention period or legal basis to state.
    expect(
      spanishLegalPendingFacts(minimalBusinessConfig().business_profile, FULL_SPANISH_LEGAL, { hasContactForm: false }),
    ).toEqual([]);
  });

  it("the privacy policy names exactly the data the form collects", () => {
    const site = spanishSite({
      lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email", "phone"] },
    });
    const privacy = legalTextOf(site.pages, "/privacidad");
    const what = privacy.sections.find((section) => section.heading === "Qué datos tratamos y para qué")!;
    expect(what.body).toContain("nombre, correo electrónico, teléfono, el mensaje que escribas");
  });

  it("makes no claim about photo ownership or legal review", () => {
    const text = allLegalText(spanishSite({ legal_profile: FULL_SPANISH_LEGAL })).toLowerCase();
    for (const claim of ["abogado", "propiedad intelectual", "fotograf", "cumple", "garantiza"]) {
      expect(text).not.toContain(claim);
    }
  });
});
