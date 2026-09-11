// LR-08 regression coverage: internal briefing/strategy language must
// never survive into customer-facing copy.
import { describe, expect, it } from "vitest";
import { sanitizeCustomerCopy } from "./copy.ts";

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
