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
