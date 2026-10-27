import { describe, expect, it } from "vitest";
import {
  buildPublicLeadPayload,
  HONEYPOT_FIELD_NAME,
  leadSourceUrl,
  newSubmissionId,
  SOURCE_URL_MAX_LENGTH,
  SubmissionIdTracker,
  TIMING_FIELD_NAME,
} from "./leadPayload.ts";

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

  it("takes source_url from the page, never from a form field (C2.3)", () => {
    const fromPage = buildPublicLeadPayload({ fields: {}, sourceUrl: "https://example.com/contacto" });
    const fromField = buildPublicLeadPayload({ fields: { source_url: "https://attacker.example/x" } });

    expect(fromPage.source_url).toBe("https://example.com/contacto");
    expect(fromField.source_url).toBeUndefined();
  });
});

describe("leadSourceUrl (C2.3)", () => {
  it("prefers the page's canonical URL", () => {
    expect(
      leadSourceUrl({ href: "https://x.pages.dev/privacidad/", canonicalHref: "https://taller.example/privacidad/" }),
    ).toBe("https://taller.example/privacidad/");
  });

  it("falls back to the current location when there is no usable canonical", () => {
    expect(leadSourceUrl({ href: "https://x.pages.dev/" })).toBe("https://x.pages.dev/");
    expect(leadSourceUrl({ href: "https://x.pages.dev/", canonicalHref: "/relative" })).toBe("https://x.pages.dev/");
    expect(leadSourceUrl({ href: "https://x.pages.dev/", canonicalHref: "javascript:alert(1)" })).toBe(
      "https://x.pages.dev/",
    );
  });

  it("drops the query string, the fragment and any credentials", () => {
    expect(
      leadSourceUrl({ href: "https://user:pw@taller.example/contacto/?utm_source=x&token=secret#formulario" }),
    ).toBe("https://taller.example/contacto/");
  });

  it("refuses anything but http(s), and URLs the API would reject as too long", () => {
    expect(leadSourceUrl({ href: "file:///etc/passwd" })).toBeUndefined();
    expect(leadSourceUrl({ href: "data:text/html,x" })).toBeUndefined();
    expect(leadSourceUrl({ href: `https://taller.example/${"a".repeat(SOURCE_URL_MAX_LENGTH)}` })).toBeUndefined();
  });
});

describe("newSubmissionId (C2.3)", () => {
  const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

  it("uses crypto.randomUUID when the page has it", () => {
    expect(newSubmissionId({ randomUUID: () => "11111111-1111-4111-8111-111111111111" })).toBe(
      "11111111-1111-4111-8111-111111111111",
    );
    expect(newSubmissionId()).toMatch(uuidV4);
  });

  it("falls back to getRandomValues on pages without randomUUID", () => {
    const id = newSubmissionId({ getRandomValues: (array) => array.fill(0xff) });

    expect(id).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(id).toMatch(uuidV4);
  });

  it("returns undefined, so the lead is sent without one, when there is no crypto at all", () => {
    expect(newSubmissionId({})).toBeUndefined();
  });
});

describe("SubmissionIdTracker (C2.3)", () => {
  function tracker() {
    let next = 0;
    return new SubmissionIdTracker<object>(() => `id-${++next}`);
  }
  const content = buildPublicLeadPayload({ fields: { name: "Ana", email: "ana@example.com", message: "Hola" } });

  it("reuses the id for a retry of the same content", () => {
    const ids = tracker();
    const form = {};

    expect(ids.idFor(form, content)).toBe("id-1");
    expect(ids.idFor(form, { ...content })).toBe("id-1");
  });

  it("gives changed content a new id: it is a new submission", () => {
    const ids = tracker();
    const form = {};
    ids.idFor(form, content);

    expect(ids.idFor(form, { ...content, message: "Hola, otra cosa" })).toBe("id-2");
  });

  it("starts over after a successful send is forgotten", () => {
    const ids = tracker();
    const form = {};
    ids.idFor(form, content);
    ids.forget(form);

    expect(ids.idFor(form, content)).toBe("id-2");
  });

  it("never shares an id between two forms", () => {
    const ids = tracker();

    expect(ids.idFor({}, content)).not.toBe(ids.idFor({}, content));
  });

  it("ignores a submission_id already on the payload when comparing content", () => {
    const ids = tracker();
    const form = {};
    ids.idFor(form, content);

    expect(ids.idFor(form, { ...content, submission_id: "something-else" })).toBe("id-1");
  });
});
