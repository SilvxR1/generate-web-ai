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
  /** C2.3: one id per logical submission, reused by its retries (the API
   * stores at most one lead per business and submission_id). */
  submission_id?: string;
}

/** PublicLeadCreateRequest.source_url's max_length: a longer value would
 * fail validation and lose the whole lead, so it's left out instead. */
export const SOURCE_URL_MAX_LENGTH = 2048;

/**
 * C2.3: the page a lead was sent from, for `source_url`. The page's
 * canonical URL when it has one (an absolute http(s) URL), otherwise the
 * current location. Query string, fragment and credentials are always
 * dropped (campaign or session parameters are never stored with a lead).
 * Comes from the page itself, never from a form field, and the server
 * still validates it like any other value.
 */
export function leadSourceUrl({ href, canonicalHref }: { href: string; canonicalHref?: string | null }): string | undefined {
  for (const candidate of [canonicalHref, href]) {
    const url = toSourceUrl(candidate);
    if (url) return url;
  }
  return undefined;
}

function toSourceUrl(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return undefined;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return undefined;
  url.username = "";
  url.password = "";
  url.search = "";
  url.hash = "";
  const value = url.toString();
  return value.length <= SOURCE_URL_MAX_LENGTH ? value : undefined;
}

interface CryptoLike {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
}

/** A random (version 4) UUID, the format PublicLeadCreateRequest.submission_id
 * expects. `crypto.randomUUID` only exists on https/localhost pages, hence
 * the getRandomValues fallback; with neither, undefined (the lead is sent
 * without one, exactly as before). */
export function newSubmissionId(
  cryptoImpl: CryptoLike | undefined = (globalThis as { crypto?: CryptoLike }).crypto,
): string | undefined {
  if (typeof cryptoImpl?.randomUUID === "function") return cryptoImpl.randomUUID();
  if (typeof cryptoImpl?.getRandomValues !== "function") return undefined;
  const bytes = cryptoImpl.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * C2.3: which submission_id each form's next attempt uses. An attempt
 * with exactly the same content as the previous one is a retry and reuses
 * its id, so the API can recognise a retry after a timeout or a lost
 * response. Changed content is a new submission and gets a new id.
 * `forget` drops a form's id once it has been sent successfully. Ids live
 * only in memory (a WeakMap keyed by the form), never in storage.
 */
export class SubmissionIdTracker<Key extends object> {
  readonly #attempts = new WeakMap<Key, { id: string | undefined; fingerprint: string }>();
  readonly #generate: () => string | undefined;

  constructor(generate: () => string | undefined = newSubmissionId) {
    this.#generate = generate;
  }

  idFor(key: Key, payload: PublicLeadPayload): string | undefined {
    const fingerprint = JSON.stringify({ ...payload, submission_id: undefined });
    const previous = this.#attempts.get(key);
    if (previous && previous.fingerprint === fingerprint) return previous.id;
    const id = this.#generate();
    this.#attempts.set(key, { id, fingerprint });
    return id;
  }

  forget(key: Key): void {
    this.#attempts.delete(key);
  }
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
  /** The page the form is on (see leadSourceUrl), resolved by the caller. */
  sourceUrl?: string;
}

/**
 * Never includes `tenant_id` — this payload has no such field at all,
 * by construction, matching the backend's own "tenant_id is derived
 * server-side from the business row, never trusted from the caller"
 * boundary (app.routers.public.create_public_lead). There is no code
 * path in this function, or in LeadSubmission.astro, that reads or
 * forwards a tenant id from anywhere.
 */
export function buildPublicLeadPayload({
  fields,
  serviceLabel,
  sourceUrl,
}: BuildPublicLeadPayloadOptions): PublicLeadPayload {
  const subject = cleanString(fields.subject) ?? cleanString(serviceLabel) ?? cleanString(fields.service);

  return {
    name: cleanString(fields.name),
    email: cleanString(fields.email),
    phone: cleanString(fields.phone),
    message: cleanString(fields.message),
    subject,
    // C2.3: from the page itself (leadSourceUrl), never from a form field.
    source_url: cleanString(sourceUrl),
    consent: fields.consent === "true" || fields.consent === "on",
    // Always a string (never omitted) — matches
    // PublicLeadCreateRequest.company_website's own `= ""` default.
    company_website: fields[HONEYPOT_FIELD_NAME] ?? "",
    rendered_at: cleanString(fields[TIMING_FIELD_NAME]),
  };
}
