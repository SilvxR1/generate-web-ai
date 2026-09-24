// A8.2.3 backward-compatibility guard: generateSiteConfig(config, assets)
// with NO creative direction must keep producing exactly the SiteConfig it
// produced before directions existed. fixtures/no-direction-golden.json
// was recorded from the pre-A8.2.3 generator across a deliberately varied
// matrix (every design family and gallery placement, with and without
// brand, photos, hero candidates, contact and WhatsApp); any change to the
// no-direction output fails here.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { describe, expect, it } from "vitest";
import type { BusinessAssetInput } from "./assets.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";

function photo(category: BusinessAssetInput["category"], n: number, origin: BusinessAssetInput["origin"] = "uploaded"): BusinessAssetInput {
  return { kind: "image", category, origin, storage_url: `https://cdn.example.com/${category}-${n}.jpg`, alt_text: null };
}

const brand = {
  colors: { primary: "#b5651d", secondary: "#6b4226", accent: "#e8a33d", background: "#fdf8f3", foreground: "#3a2e28" },
  typography: { sans: "Inter, sans-serif" },
};

export const GOLDEN_MATRIX: Record<string, [BusinessConfig, BusinessAssetInput[]]> = {
  reforma_no_assets: [exampleReformaValenciaConfig, []],
  reforma_projects_and_hero: [
    exampleReformaValenciaConfig,
    [photo("hero_candidate", 0), ...[1, 2, 3, 4, 5].map((n) => photo("project", n)), photo("gallery", 6, "generated")],
  ],
  handmade_shop_38_photos: [
    {
      business_profile: {
        industry: "other",
        name: "Taller de Hilo",
        slug: "taller-de-hilo",
        description: "Piezas de crochet hechas a mano.",
        services: [{ id: "encargos", name: "Encargos", description: "Piezas por encargo." }],
        contact: { email: "hola@example.com" },
      },
      brand: { ...brand, visual_style: "handmade" },
    } as BusinessConfig,
    Array.from({ length: 38 }, (_, n) => photo("gallery", n)),
  ],
  clinic_unbranded: [
    {
      business_profile: {
        industry: "clinic",
        name: "Clínica Norte",
        slug: "clinica-norte",
        services: [{ id: "consulta", name: "Consulta", description: "Consulta general." }],
        contact: { phone: "+34 600 111 222" },
        service_area: ["Valencia"],
      },
    } as BusinessConfig,
    [photo("facility", 1), photo("team", 2)],
  ],
  restaurant_with_hero: [
    {
      business_profile: {
        industry: "restaurant",
        name: "Casa Marea",
        slug: "casa-marea",
        description: "Cocina de mercado.",
        contact: { phone: "+34 611 000 000", address: { street_address: "Calle Mar 1", locality: "Valencia" } },
      },
      brand,
    } as BusinessConfig,
    [photo("hero_candidate", 0), photo("gallery", 1), photo("gallery", 2)],
  ],
  minimal: [{ business_profile: { industry: "other", name: "Taller Martinez", slug: "taller-martinez" } } as BusinessConfig, []],
  whatsapp_only: [
    {
      business_profile: { industry: "ecommerce", name: "Tienda Uno", slug: "tienda-uno" },
      whatsapp: { enabled: true, phone_number: "+34600123456", show_contact_cta: false },
    } as BusinessConfig,
    [photo("product", 1)],
  ],
};

describe("generateSiteConfig — no-direction output is unchanged", () => {
  it("matches the recorded pre-A8.2.3 golden output for every matrix case", async () => {
    const output = Object.fromEntries(
      Object.entries(GOLDEN_MATRIX).map(([name, [config, assets]]) => [name, generateSiteConfig(config, assets)]),
    );
    await expect(`${JSON.stringify(output, null, 2)}\n`).toMatchFileSnapshot("../fixtures/no-direction-golden.json");
  });
});
