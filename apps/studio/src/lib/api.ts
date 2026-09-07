import type { BusinessConfig, BusinessVertical } from "@generate-web-ai/business-config-types";
import type { SiteConfig } from "@generate-web-ai/site-config";
import type { WorkflowConfig } from "@generate-web-ai/workflow-config-types";

// The only backend this dashboard talks to — see apps/api.
export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

/**
 * Every error path in apps/api renders `{"error": {"code", "message", "details"?}}`
 * (see app/errors.py) — ApiError carries that shape through so callers can
 * branch on `code` instead of parsing prose, while `message` stays available
 * for a fallback display and `details` for anything worth showing a developer.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, options: { code: string; status: number; details?: unknown }) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
  }
}

/** Thrown when `fetch` itself fails (backend unreachable, offline, CORS) —
 * distinct from ApiError, which means the backend *did* respond. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : "Network request failed.");
    this.name = "NetworkError";
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; details?: unknown };
}

/** Shared fetch + error handling for every request below — resolves to
 * the raw, successful Response so callers can decide how (or whether)
 * to parse a body: requestJson parses one, requestVoid doesn't (for
 * endpoints like DELETE that return 204 No Content, where calling
 * response.json() would throw on the empty body). */
async function sendRequest(path: string, init: RequestInit, tenantId: string): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenantId,
        ...init.headers,
      },
    });
  } catch (cause) {
    throw new NetworkError(cause);
  }

  if (!response.ok) {
    let body: ErrorBody = {};
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      // Non-JSON error body (e.g. a proxy's plain-text 502) — fall
      // through to the generic message below.
    }
    throw new ApiError(body.error?.message ?? `Request failed with status ${response.status}.`, {
      code: body.error?.code ?? "http_error",
      status: response.status,
      details: body.error?.details,
    });
  }

  return response;
}

async function requestJson<T>(path: string, init: RequestInit, tenantId: string): Promise<T> {
  const response = await sendRequest(path, init, tenantId);
  return (await response.json()) as T;
}

async function requestVoid(path: string, init: RequestInit, tenantId: string): Promise<void> {
  await sendRequest(path, init, tenantId);
}

export interface AnalyzeBusinessResponse {
  proposed_config: BusinessConfig | null;
  missing_information: string[];
  questions: string[];
}

export function analyzeBusiness(briefing: string, tenantId: string): Promise<AnalyzeBusinessResponse> {
  return requestJson<AnalyzeBusinessResponse>(
    "/businesses/analyze",
    { method: "POST", body: JSON.stringify({ briefing }) },
    tenantId,
  );
}

export interface CreateBusinessPayload {
  name: string;
  slug: string;
  vertical: BusinessVertical;
  raw_description: string;
  status: "draft" | "active" | "paused";
  config: BusinessConfig | null;
}

export interface CreatedBusiness {
  id: string;
  name: string;
  slug: string;
  status: string;
  raw_description: string;
  /** The config exactly as persisted — the preview step generates its
   * website/workflow previews from *this*, never from the local draft,
   * so the preview always matches what the engines will actually see. */
  config: BusinessConfig | null;
}

export function createBusiness(payload: CreateBusinessPayload, tenantId: string): Promise<CreatedBusiness> {
  return requestJson<CreatedBusiness>("/businesses", { method: "POST", body: JSON.stringify(payload) }, tenantId);
}

export function updateBusiness(
  businessId: string,
  payload: CreateBusinessPayload,
  tenantId: string,
): Promise<CreatedBusiness> {
  return requestJson<CreatedBusiness>(
    `/businesses/${businessId}`,
    { method: "PUT", body: JSON.stringify(payload) },
    tenantId,
  );
}

/** Reopens an existing business — the same shape POST /businesses
 * returns, so the result can feed straight into PreviewStep exactly as
 * a freshly-created business does (no second, dashboard-only
 * management UI). */
export function getBusiness(businessId: string, tenantId: string): Promise<CreatedBusiness> {
  return requestJson<CreatedBusiness>(`/businesses/${businessId}`, { method: "GET" }, tenantId);
}

/** Permanently deletes a business and everything the backend cascades
 * off it (website, automation, leads, ...) — see DELETE
 * /businesses/{id}'s own docstring (apps/api's app.routers.businesses)
 * for exactly what that includes and the deliberate scope limits
 * around remote n8n/Cloudflare cleanup. Resolves to nothing on success
 * (the backend returns 204 No Content); rejects with ApiError/
 * NetworkError on failure, same as every other call here — deletion
 * never happens just because this promise was awaited without a
 * try/catch around it. */
export function deleteBusiness(businessId: string, tenantId: string): Promise<void> {
  return requestVoid(`/businesses/${businessId}`, { method: "DELETE" }, tenantId);
}

// --- Business dashboard listing -----------------------------------------
//
// GET /business-summaries (app.routers.businesses) is Studio's home
// screen: every business this tenant owns, plus a lightweight,
// batch-loaded snapshot of each one's *persisted* website/automation
// state — deliberately not the full BusinessConfig (see
// BusinessSummary's own docstring on the backend), so this dashboard
// never duplicates BusinessConfig state or infers website/automation
// status from it. Lives on its own /business-summaries path rather
// than nested under /businesses (e.g. /businesses/summary) — the
// latter used to collide with GET /businesses/{businessId} and get
// misrouted as a business lookup with businessId="summary".

export interface BusinessLocationSummary {
  city: string;
  region: string | null;
  country: string;
  postal_code: string | null;
}

export interface BusinessWebsiteSummary {
  status: WebsiteStatus;
  live_url: string | null;
}

export interface BusinessAutomationSummary {
  status: AutomationStatus;
  active: boolean;
}

export interface BusinessSummary {
  id: string;
  name: string;
  slug: string;
  vertical: BusinessVertical;
  status: "draft" | "active" | "paused";
  location: BusinessLocationSummary | null;
  created_at: string;
  updated_at: string;
  /** Null exactly when GET .../website has never been called for real
   * yet, i.e. this business has never been published. */
  website: BusinessWebsiteSummary | null;
  /** Null exactly when GET .../automation has never been called for
   * real yet, i.e. this business has never had automation activated. */
  automation: BusinessAutomationSummary | null;
}

export function listBusinessSummaries(tenantId: string): Promise<BusinessSummary[]> {
  return requestJson<BusinessSummary[]>("/business-summaries", { method: "GET" }, tenantId);
}

// --- Workflow preview --------------------------------------------------
//
// WorkflowConfig itself comes from @generate-web-ai/workflow-config-types
// (generated from apps/api's Pydantic model) — no hand-mirrored shape
// here to drift from it.

export function getWorkflowPreview(businessId: string, tenantId: string): Promise<WorkflowConfig | null> {
  return requestJson<WorkflowConfig | null>(`/businesses/${businessId}/workflow-preview`, { method: "GET" }, tenantId);
}

// --- Automation state -----------------------------------------------------
//
// Activate (POST .../automation/activate) is the one human-triggered
// action that turns a preview into a real, active n8n workflow —
// deactivate (POST .../automation/deactivate) its counterpart — never
// called automatically. GET .../automation reads the same *persisted*
// state (app.db.models.workflow.Workflow on the backend) without
// touching n8n, so a reload of the page reflects reality rather than
// this dashboard's own memory. Every response here is provider-neutral:
// no n8n workflow JSON, no credential, ever.

export type AutomationStatus = "draft" | "provisioning" | "active" | "inactive" | "error";

export interface AutomationState {
  workflow_id: string;
  remote_id: string | null;
  name: string;
  status: AutomationStatus;
  active: boolean;
  version: number;
  required_capabilities: string[];
  activated_at: string | null;
  updated_at: string | null;
}

export function getAutomationState(businessId: string, tenantId: string): Promise<AutomationState | null> {
  return requestJson<AutomationState | null>(`/businesses/${businessId}/automation`, { method: "GET" }, tenantId);
}

export function activateAutomation(businessId: string, tenantId: string): Promise<AutomationState> {
  return requestJson<AutomationState>(`/businesses/${businessId}/automation/activate`, { method: "POST" }, tenantId);
}

export function deactivateAutomation(businessId: string, tenantId: string): Promise<AutomationState> {
  return requestJson<AutomationState>(`/businesses/${businessId}/automation/deactivate`, { method: "POST" }, tenantId);
}

// --- Website publishing -----------------------------------------------
//
// Publish (POST .../website/publish) is the one human-triggered action
// that turns a website *preview* into a real, live static site — never
// called automatically. Its body is the exact SiteConfig
// `generateSiteConfig()` already produced for this same preview (see
// PreviewStep.tsx) — the backend never recomputes it, so the published
// site can't drift from what was shown before publishing. GET
// .../website reads the same persisted state without publishing
// anything. Every response here is provider-neutral: no hosting
// provider payload, no credential, ever.

export type WebsiteStatus = "draft" | "building" | "live" | "failed";

export interface WebsiteState {
  status: WebsiteStatus;
  live_url: string | null;
  deployment_id: string | null;
  deployed_at: string | null;
  updated_at: string | null;
}

export function getWebsiteState(businessId: string, tenantId: string): Promise<WebsiteState | null> {
  return requestJson<WebsiteState | null>(`/businesses/${businessId}/website`, { method: "GET" }, tenantId);
}

export function publishWebsite(businessId: string, tenantId: string, siteConfig: SiteConfig): Promise<WebsiteState> {
  return requestJson<WebsiteState>(
    `/businesses/${businessId}/website/publish`,
    { method: "POST", body: JSON.stringify(siteConfig) },
    tenantId,
  );
}

// --- Leads --------------------------------------------------------------
//
// GET .../leads (app.routers.businesses) reads persisted Lead rows,
// tenant- and business-scoped server-side (LeadRepository) — most recent
// first. PATCH .../leads/{id}/status is the one write path onto a lead:
// it changes `status` and nothing else (the backend's
// LeadStatusUpdateRequest rejects any other field), same tenant/business
// scoping as the read.

export type LeadStatus = "new" | "contacted" | "won" | "lost";

export interface Lead {
  id: string;
  business_id: string;
  source: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  message: string | null;
  status: LeadStatus;
  created_at: string;
}

export function getLeads(businessId: string, tenantId: string): Promise<Lead[]> {
  return requestJson<Lead[]>(`/businesses/${businessId}/leads`, { method: "GET" }, tenantId);
}

// --- Automation recommendation -----------------------------------------
//
// GET .../automation-recommendation (app.routers.businesses) is a pure,
// stateless lookup by vertical — app.domain.workflow_config.
// vertical_templates.recommended_automation_template, reused as-is on
// the backend. Never a second, Studio-side copy of the template values
// themselves: this only mirrors the wire shape the backend already
// returns, the same way every other type in this file does.

export interface AutomationRecommendation {
  lead_notifications: boolean;
  customer_acknowledgement: boolean;
  follow_up_enabled: boolean;
  follow_up_delay_hours: number;
}

export function getAutomationRecommendation(vertical: BusinessVertical, tenantId: string): Promise<AutomationRecommendation> {
  return requestJson<AutomationRecommendation>(
    `/businesses/automation-recommendation?vertical=${encodeURIComponent(vertical)}`,
    { method: "GET" },
    tenantId,
  );
}

export function updateLeadStatus(
  businessId: string,
  leadId: string,
  status: LeadStatus,
  tenantId: string,
): Promise<Lead> {
  return requestJson<Lead>(
    `/businesses/${businessId}/leads/${leadId}/status`,
    { method: "PATCH", body: JSON.stringify({ status }) },
    tenantId,
  );
}
