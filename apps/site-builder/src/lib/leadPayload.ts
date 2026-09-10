/**
 * Pure mapping from a generated Contact form's raw submitted fields to
 * the exact shape apps/api's POST /public/businesses/{id}/leads expects
 * (app.schemas.public.PublicLeadCreateRequest) — kept dependency-free
 * (no DOM, no fetch) so it's unit-testable without a browser and so the
 * actual wire contract lives in one place, not duplicated across the
 * Astro component that calls it.
 *
 * Field-name reconciliation: the generated form's `service` field (a
 * dropdown of the business's own services, built by
 * @generate-web-ai/website-generator's FORM_FIELD_BUILDERS) has no
 * counterpart in the backend's Lead schema — the backend has `subject`
 * (free text: "what service/topic the lead is about"), not a
 * service-id enum. `serviceLabel` (the selected <option>'s visible
 * text, e.g. "Reforma de cocina" — never its `value`, which is only a
 * slug id) is what actually carries that meaning across; an explicit
 * `subject` field (if the form ever grows one) always wins over it.
 *
 * The honeypot (`HONEYPOT_FIELD_NAME`) and submission-timing fields are
 * deliberately not part of the generated form's data-driven
 * `ContactFormConfig.fields` (packages/site-config) — they're a pure
 * transport/anti-spam concern of *this* submission path, not business
 * content, so they're never seen by anything that reads a SiteConfig.
 */

/** The DOM field name for the honeypot input (see Contact.astro) —
 * deliberately not named anything resembling the backend's own
 * `company_website` field, so a browser's address/company autofill
 * heuristics are less likely to fill it in for a real visitor. */
export const HONEYPOT_FIELD_NAME = "hp_field";

/** The DOM field name carrying the client-captured render timestamp
 * (ISO 8601, see Contact.astro) — mapped 1:1 onto the backend's
 * `rendered_at`. */
export const TIMING_FIELD_NAME = "rendered_at";

export interface PublicLeadPayload {
  name?: string;
  email?: string;
  phone?: string;
  message?: string;
  subject?: string;
  source_url?: string;
  consent: boolean;
  company_website: string;
  rendered_at?: string;
}

/** `undefined`/empty-string safe: FormData reports an unfilled optional
 * text field as `""`, but the backend's optional fields are `str | None`
 * — sending `""` instead of omitting the key is needless noise (and,
 * for `email` specifically, `""` would fail EmailStr validation if that
 * field were ever rendered as non-required). Every currently-generated
 * field is marked `required` in the DOM (browser-native validation
 * blocks an empty required field from ever reaching `submit`), so this
 * is defense-in-depth, not a workaround for an expected empty value. */
function cleanString(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? value : undefined;
}

export interface BuildPublicLeadPayloadOptions {
  /** Raw `Object.fromEntries(new FormData(form).entries())` — string
   * values only (file fields are presentational-only in this form, see
   * Contact.astro's own docstring, so never relevant here). */
  fields: Record<string, string>;
  /** The selected service <option>'s visible label, when the form has a
   * `service` <select> and one is chosen — resolved by the caller
   * (which has the actual <select> element), not here. */
  serviceLabel?: string;
}

/**
 * Never includes `tenant_id` — this payload has no such field at all,
 * by construction, matching the backend's own "tenant_id is derived
 * server-side from the business row, never trusted from the caller"
 * boundary (app.routers.public.create_public_lead). There is no code
 * path in this function, or in LeadSubmission.astro, that reads or
 * forwards a tenant id from anywhere.
 */
export function buildPublicLeadPayload({ fields, serviceLabel }: BuildPublicLeadPayloadOptions): PublicLeadPayload {
  const subject = cleanString(fields.subject) ?? cleanString(serviceLabel) ?? cleanString(fields.service);

  return {
    name: cleanString(fields.name),
    email: cleanString(fields.email),
    phone: cleanString(fields.phone),
    message: cleanString(fields.message),
    subject,
    source_url: cleanString(fields.source_url),
    consent: fields.consent === "true" || fields.consent === "on",
    // Always a string (never omitted) — matches
    // PublicLeadCreateRequest.company_website's own `= ""` default.
    company_website: fields[HONEYPOT_FIELD_NAME] ?? "",
    rendered_at: cleanString(fields[TIMING_FIELD_NAME]),
  };
}
