/**
 * Platform SDK (P2 Part B) — the stable runtime boundary every generated
 * site imports instead of reimplementing lead capture / analytics /
 * consent / WhatsApp itself. This exact file is written into every
 * generative workspace by app.creative.frontend_engine.workspace, never
 * authored or editable by the AI Frontend Engineer — the manifest writer
 * refuses any AI-submitted file at this path (see workspace.py's
 * RESERVED_PATHS). Mirrors the real, already-working client logic in
 * apps/site-builder/src/lib/leadPayload.ts and
 * apps/site-builder/src/components/{Analytics,CookieConsentBanner,LeadSubmission}.astro
 * — same endpoints, same event names, same consent-gating discipline —
 * so a generative and a deterministic site are indistinguishable to the
 * backend and to PlatformContract, whatever they look like to a visitor.
 *
 * `businessId`/`apiBaseUrl` are read from a `<script type="application/json"
 * id="platform-config">` tag that the build pipeline injects into every
 * HTML page AFTER the AI's own files are written (see build.py's
 * `_inject_platform_config`) — never trusted from anything the AI wrote,
 * so tenant identity stays server-authoritative regardless of what the
 * generated markup contains.
 */

// Astro prerenders every page server-side (Node.js) before any client
// script runs — this module is written into src/lib/, importable from
// both an Astro component's server-side frontmatter *and* a client
// <script>, so every browser-API access below is guarded by `isBrowser`
// rather than assumed. Reading `document`/`localStorage`/`window` at
// module-load time (the bug this comment replaces) crashes Astro's
// static build with "document is not defined" the moment anything
// imports this module from frontmatter — config/consent are therefore
// computed lazily, on first real (client-side) use, never eagerly.
const isBrowser = typeof document !== "undefined";

export const HONEYPOT_FIELD_NAME = "hp_field";
export const TIMING_FIELD_NAME = "rendered_at";

interface PlatformConfig {
  businessId?: string;
  apiBaseUrl?: string;
}

function readConfig(): PlatformConfig {
  if (!isBrowser) return {};
  const raw = document.getElementById("platform-config")?.textContent;
  if (!raw) return {};
  try {
    return JSON.parse(raw) as PlatformConfig;
  } catch {
    return {};
  }
}

function apiUrl(path: string): string | null {
  const config = readConfig();
  if (!config.businessId || !config.apiBaseUrl) return null;
  return `${config.apiBaseUrl}/public/businesses/${config.businessId}${path}`;
}

// --- Consent -------------------------------------------------------------

export type ConsentCategory = "analytics" | "marketing" | "preferences";
type ConsentRecord = { necessary: true } & Record<ConsentCategory, boolean> & { updatedAt: string };

const CONSENT_STORAGE_KEY = "gwa-consent";

function readStoredConsent(): ConsentRecord | null {
  if (!isBrowser) return null;
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ConsentRecord) : null;
  } catch {
    return null;
  }
}

let currentConsent: ConsentRecord | null | undefined; // undefined = not yet read this session

function consent(): ConsentRecord | null {
  if (currentConsent === undefined) currentConsent = readStoredConsent();
  return currentConsent;
}

/** Never preselected, never fails open — absence of a stored decision
 * reads as "not granted" for every optional category. */
export function getConsent(category: "necessary" | ConsentCategory): boolean {
  if (category === "necessary") return true;
  const record = consent();
  return Boolean(record && record[category]);
}

export function setConsent(categories: Partial<Record<ConsentCategory, boolean>>): void {
  if (!isBrowser) return;
  currentConsent = {
    necessary: true,
    analytics: false,
    marketing: false,
    preferences: false,
    ...categories,
    updatedAt: new Date().toISOString(),
  };
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(currentConsent));
  } catch {
    // Storage unavailable — the choice still applies for this page view.
  }
  window.dispatchEvent(new CustomEvent("gwa-consent-change", { detail: currentConsent }));
}

// --- Analytics -------------------------------------------------------------

export type AnalyticsEventType =
  | "page_view"
  | "cta_click"
  | "whatsapp_click"
  | "lead_form_started"
  | "lead_submitted"
  | "phone_click"
  | "email_click";

let analyticsQueue: [AnalyticsEventType, Record<string, string> | undefined][] = [];

function sendEvent(eventType: AnalyticsEventType, metadata?: Record<string, string>): void {
  if (!isBrowser) return;
  const url = apiUrl("/events");
  if (!url) return;
  const body: Record<string, unknown> = { event_type: eventType, source_page: window.location.pathname };
  if (metadata) body.metadata = metadata;
  try {
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {});
  } catch {
    // A beacon failure must never affect the page itself.
  }
}

/** Gated on analytics consent — an event fired before consent is
 * granted is queued in memory (never persisted) and flushed only if the
 * visitor later grants it. */
export function trackEvent(eventType: AnalyticsEventType, metadata?: Record<string, string>): void {
  if (!getConsent("analytics")) {
    analyticsQueue.push([eventType, metadata]);
    return;
  }
  sendEvent(eventType, metadata);
}

if (isBrowser) {
  window.addEventListener("gwa-consent-change", () => {
    if (!getConsent("analytics")) return;
    const pending = analyticsQueue;
    analyticsQueue = [];
    pending.forEach(([eventType, metadata]) => sendEvent(eventType, metadata));
  });
}

// --- Lead submission ---------------------------------------------------

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

function cleanString(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  return value.trim().length > 0 ? value : undefined;
}

/** Submits a lead to the real, public, tenant-scoped Lead API — the same
 * wire contract apps/site-builder's LeadSubmission.astro already uses.
 * Returns true only on a real 2xx response; never simulates success. */
export async function submitLead(fields: Record<string, string>, serviceLabel?: string): Promise<boolean> {
  const url = apiUrl("/leads");
  if (!url) return false;

  const subject = cleanString(fields.subject) ?? cleanString(serviceLabel) ?? cleanString(fields.service);
  const payload: PublicLeadPayload = {
    name: cleanString(fields.name),
    email: cleanString(fields.email),
    phone: cleanString(fields.phone),
    message: cleanString(fields.message),
    subject,
    source_url: cleanString(fields.source_url ?? (isBrowser ? window.location.href : undefined)),
    consent: fields.consent === "true" || fields.consent === "on",
    company_website: fields[HONEYPOT_FIELD_NAME] ?? "",
    rendered_at: cleanString(fields[TIMING_FIELD_NAME]),
  };

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.ok) {
      trackEvent("lead_submitted");
      // A literal event-name string (not a renameable identifier)
      // survives minification, unlike a bundled local function name —
      // this is what app.qa.platform_contract's lead-wiring check
      // actually scans for, the same convention
      // apps/site-builder/src/components/LeadSubmission.astro already
      // uses for the deterministic engine.
      document.dispatchEvent(new CustomEvent("lead.submitted"));
    }
    return response.ok;
  } catch {
    return false;
  }
}

// --- WhatsApp --------------------------------------------------------------

/** Builds a real wa.me link from a phone number the backend supplied via
 * BusinessConfig — never invents a phone number. `message` is optional,
 * URL-encoded prefilled text. */
export function getWhatsAppUrl(phoneNumber: string, message?: string): string {
  const digits = phoneNumber.replace(/\D/g, "");
  return `https://wa.me/${digits}${message ? `?text=${encodeURIComponent(message)}` : ""}`;
}

// --- Click delegation (phone/email/WhatsApp click tracking) ---------------

// Global exposure under the platform's existing window.gwaConsent/
// window.gwaAnalytics names — a bundler minifies local identifiers
// (including this module's own exported function names), but never the
// string property names on an object literal assigned to `window`, so
// this is what stays reliably detectable in built output by
// app.qa.platform_contract (the same detection contract the
// deterministic engine's own Analytics.astro/CookieConsentBanner.astro
// already rely on). AI-authored code should still prefer the typed
// named imports above; this exists for platform-side verification, not
// as the primary authoring API.
declare global {
  interface Window {
    gwaConsent?: { isGranted(category: string): boolean; open(): void };
    gwaAnalytics?: { track(eventType: AnalyticsEventType, metadata?: Record<string, string>): void };
  }
}

// Every remaining module-level side effect (click delegation, the
// initial page_view beacon, the window.gwa* global exposure) is real
// browser behavior with no server-side equivalent — guarded as one
// block so importing this module from Astro server-side frontmatter
// (to read its exported types/functions) never touches a browser API
// that doesn't exist during prerender.
if (isBrowser) {
  document.addEventListener("click", (event) => {
    const target = event.target as Element | null;
    const link = target?.closest?.("a[href]");
    if (!link) return;
    const href = link.getAttribute("href") || "";
    if (href.startsWith("tel:")) trackEvent("phone_click");
    else if (href.startsWith("mailto:")) trackEvent("email_click");
    else if (href.includes("wa.me")) {
      const placement = link.closest("[data-whatsapp-floating]") ? "floating" : "contact_section";
      trackEvent("whatsapp_click", { placement });
    }
  });

  trackEvent("page_view");

  window.gwaConsent = { isGranted: (category) => getConsent(category as ConsentCategory), open: () => {} };
  window.gwaAnalytics = { track: trackEvent };
}

