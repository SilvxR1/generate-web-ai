// LR-08 regression coverage: internal briefing/strategy language must
// never survive into customer-facing copy.
import { describe, expect, it } from "vitest";
import { sanitizeCustomerCopy } from "./copy.ts";
import { generateSiteConfig } from "./generateSiteConfig.ts";

describe("sanitizeCustomerCopy", () => {
  it("returns undefined for empty/blank input", () => {
    expect(sanitizeCustomerCopy(undefined)).toBeUndefined();
    expect(sanitizeCustomerCopy(null)).toBeUndefined();
    expect(sanitizeCustomerCopy("   ")).toBeUndefined();
  });

  it("leaves ordinary customer-facing copy untouched", () => {
    const text = "Amigurumis hechos a mano, punto a punto. Descubre nuestras creaciones.";
    expect(sanitizeCustomerCopy(text)).toBe(text);
  });

  it("strips a sentence stating the business currently has no website", () => {
    const text =
      "Hacemos amigurumis artesanales. The business currently has no website yet. Contáctanos por Instagram.";
    const result = sanitizeCustomerCopy(text);
    expect(result).not.toContain("no website");
    expect(result).toContain("Hacemos amigurumis artesanales.");
    expect(result).toContain("Contáctanos por Instagram.");
  });

  it("strips a sentence about not having ecommerce/cart/payment in this first version", () => {
    const text = "Creamos piezas únicas. No ecommerce/cart/payment in this first version. Escríbenos para encargos.";
    const result = sanitizeCustomerCopy(text);
    expect(result).not.toMatch(/ecommerce/i);
    expect(result).not.toMatch(/first version/i);
  });

  it("strips a sentence naming the conversion objective", () => {
    const text = "Ropa de punto artesanal. Our conversion objective is lead capture via the contact form.";
    const result = sanitizeCustomerCopy(text);
    expect(result).not.toMatch(/conversion objective/i);
  });

  it("strips a sentence describing the website's own creation objective", () => {
    const text =
      "Vendemos amigurumis desde 2019. The objective is to create a professional digital presence for the brand.";
    const result = sanitizeCustomerCopy(text);
    expect(result).not.toMatch(/digital presence/i);
    expect(result).toContain("Vendemos amigurumis desde 2019.");
  });

  it("strips an instruction not to invent reviews", () => {
    const text = "Hacemos tejidos a mano. Do not invent reviews or testimonials.";
    const result = sanitizeCustomerCopy(text);
    expect(result).not.toMatch(/do not invent/i);
  });

  it("returns undefined when every sentence is internal strategy commentary", () => {
    const text = "The business currently has no website yet. No ecommerce/cart/payment in this first version.";
    expect(sanitizeCustomerCopy(text)).toBeUndefined();
  });

  it("does not strip a legitimate sentence that merely mentions 'no' in a customer-facing way", () => {
    const text = "Sin pedido mínimo — escríbenos y lo hacemos a medida.";
    expect(sanitizeCustomerCopy(text)).toBe(text);
  });
});

// C3: the Spanish briefing that reached the live Cositas y Puntos site
// verbatim. The patterns above were English-only.
const COSITAS_DESCRIPTION =
  "Pequeña marca artesanal española especializada en la creación de amigurumis hechos a mano mediante crochet. " +
  "Actualmente no dispone de página web; su principal presencia online es Instagram, donde publica fotografías reales de sus trabajos. " +
  "El objetivo es crear una presencia digital profesional en formato catálogo/portfolio + contacto/encargo (sin ecommerce, " +
  "carrito ni pago online en esta primera versión), donde la conversión principal es contactar con la marca para consultar o " +
  "realizar un encargo. Valores a transmitir: artesanía, cercanía, creatividad, cuidado por los detalles, personalidad, " +
  "confianza y el carácter único de cada creación.";
const COSITAS_TARGET_CUSTOMERS =
  "Principalmente personas que buscan amigurumis, regalos artesanales, regalos originales o personalizados y productos hechos a mano. " +
  "Se espera que una parte importante de los visitantes llegue desde Instagram y redes sociales (prioridad móvil).";
const COSITAS_SERVICE =
  "Creación de amigurumis hechos a mano mediante crochet. Productos artesanales, cada creación con carácter único. " +
  "No se han proporcionado precios, tiempos de fabricación, disponibilidad ni condiciones de envío.";
const INTERNAL_PHRASES =
  /no dispone de página web|presencia online es Instagram|El objetivo es|primera versión|conversión principal|Valores a transmitir|Se espera que|prioridad móvil|No se han proporcionado/i;

describe("sanitizeCustomerCopy (Spanish briefing)", () => {
  it("keeps only the customer-facing sentence of the real Cositas description", () => {
    expect(sanitizeCustomerCopy(COSITAS_DESCRIPTION)).toBe(
      "Pequeña marca artesanal española especializada en la creación de amigurumis hechos a mano mediante crochet.",
    );
  });

  it("drops the visitor-acquisition note from the audience text", () => {
    expect(sanitizeCustomerCopy(COSITAS_TARGET_CUSTOMERS)).toBe(
      "Principalmente personas que buscan amigurumis, regalos artesanales, regalos originales o personalizados y productos hechos a mano.",
    );
  });

  it("drops a note about information the business has not provided", () => {
    expect(sanitizeCustomerCopy(COSITAS_SERVICE)).toBe(
      "Creación de amigurumis hechos a mano mediante crochet. Productos artesanales, cada creación con carácter único.",
    );
  });

  it("leaves ordinary Spanish customer copy untouched", () => {
    const text =
      "Cada pieza se teje a mano en L'Eliana. Hacemos encargos personalizados: cuéntanos tu idea y te enviamos presupuesto.";
    expect(sanitizeCustomerCopy(text)).toBe(text);
  });
});

describe("generated site never publishes the briefing", () => {
  const site = generateSiteConfig({
    business_profile: {
      industry: "other",
      name: "Cositas y Puntos",
      slug: "cositas-y-puntos",
      description: COSITAS_DESCRIPTION,
      target_customers: COSITAS_TARGET_CUSTOMERS,
      services: [{ id: "amigurumis", name: "Amigurumis artesanales hechos a mano", description: COSITAS_SERVICE }],
    },
    lead_management: { enabled: true, sources: ["website_form"], required_fields: ["name", "email"] },
  });

  it("in any block or in the SEO metadata", () => {
    expect(JSON.stringify(site)).not.toMatch(INTERNAL_PHRASES);
  });

  it("while keeping the audience and the service description", () => {
    const text = JSON.stringify(site);
    expect(text).toContain("Principalmente personas que buscan amigurumis");
    expect(text).toContain("Productos artesanales, cada creación con carácter único.");
  });
});
