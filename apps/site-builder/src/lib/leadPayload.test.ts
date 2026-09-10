import { describe, expect, it } from "vitest";
import { buildPublicLeadPayload, HONEYPOT_FIELD_NAME, TIMING_FIELD_NAME } from "./leadPayload.ts";

describe("buildPublicLeadPayload", () => {
  it("maps the common fields straight through", () => {
    const payload = buildPublicLeadPayload({
      fields: { name: "Ana Ruiz", email: "ana@example.com", phone: "+34600000000", message: "Necesito presupuesto." },
    });

    expect(payload.name).toBe("Ana Ruiz");
    expect(payload.email).toBe("ana@example.com");
    expect(payload.phone).toBe("+34600000000");
    expect(payload.message).toBe("Necesito presupuesto.");
  });

  it("maps the service select's label to subject, not its raw slug value", () => {
    const payload = buildPublicLeadPayload({
      fields: { name: "Ana", email: "ana@example.com", service: "cocina-integral" },
      serviceLabel: "Reforma de cocina integral",
    });

    expect(payload.subject).toBe("Reforma de cocina integral");
    expect(payload.subject).not.toContain("cocina-integral");
  });

  it("prefers an explicit subject field over the service label when both are present", () => {
    const payload = buildPublicLeadPayload({
      fields: { subject: "Consulta general", service: "cocina-integral" },
      serviceLabel: "Reforma de cocina integral",
    });

    expect(payload.subject).toBe("Consulta general");
  });

  it("falls back to the raw service value when no label was resolved", () => {
    const payload = buildPublicLeadPayload({ fields: { service: "cocina-integral" } });

    expect(payload.subject).toBe("cocina-integral");
  });

  it("omits subject entirely when neither subject, service label, nor service value exist", () => {
    const payload = buildPublicLeadPayload({ fields: { name: "Ana" } });

    expect(payload.subject).toBeUndefined();
  });

  it("maps the honeypot field to company_website", () => {
    const payload = buildPublicLeadPayload({ fields: { [HONEYPOT_FIELD_NAME]: "a bot filled this" } });

    expect(payload.company_website).toBe("a bot filled this");
  });

  it("defaults company_website to an empty string when the honeypot was left untouched", () => {
    const payload = buildPublicLeadPayload({ fields: { name: "Ana" } });

    expect(payload.company_website).toBe("");
  });

  it("maps the timing field to rendered_at", () => {
    const timestamp = "2026-01-01T12:00:00.000Z";
    const payload = buildPublicLeadPayload({ fields: { [TIMING_FIELD_NAME]: timestamp } });

    expect(payload.rendered_at).toBe(timestamp);
  });

  it("treats a checked consent checkbox (on/true) as consent given", () => {
    expect(buildPublicLeadPayload({ fields: { consent: "on" } }).consent).toBe(true);
    expect(buildPublicLeadPayload({ fields: { consent: "true" } }).consent).toBe(true);
  });

  it("defaults consent to false when no consent field was submitted at all — never inferred true", () => {
    const payload = buildPublicLeadPayload({ fields: { name: "Ana" } });

    expect(payload.consent).toBe(false);
  });

  it("normalizes an unfilled optional field (empty string) to undefined rather than sending blank strings", () => {
    const payload = buildPublicLeadPayload({ fields: { name: "Ana", message: "   " } });

    expect(payload.message).toBeUndefined();
  });

  it("never includes a tenant_id field under any input", () => {
    const payload = buildPublicLeadPayload({
      fields: { name: "Ana", tenant_id: "should-be-ignored", email: "ana@example.com" },
    });

    expect(payload).not.toHaveProperty("tenant_id");
    expect(Object.keys(payload)).not.toContain("tenant_id");
  });

  it("carries source_url through untouched", () => {
    const payload = buildPublicLeadPayload({ fields: { source_url: "https://example.com/contacto" } });

    expect(payload.source_url).toBe("https://example.com/contacto");
  });
});
