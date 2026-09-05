// Regression coverage for the empty/missing SEO description bug: a
// BusinessConfig with no explicit website.seo.description (or an
// explicitly blank one) must still produce a non-empty
// SiteConfig.seo.description, via a deterministic name/location-based
// fallback — never AI-generated copy.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
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
