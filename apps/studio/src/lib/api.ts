import type { BusinessConfig, BusinessVertical, CreativeConfig } from "@generate-web-ai/business-config-types";
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

export type WebsiteStatus = "draft" | "building" | "live" | "failed" | "inactive";

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

/** Deactivate (POST .../website/deactivate) is publish's counterpart —
 * takes a *currently live* site down for real on the hosting provider
 * (never just a local status flip; see the backend's
 * app.publishing.service.unpublish_website docstring), then reports
 * `status: "inactive"` with `live_url: null`. Republishing afterward
 * (publishWebsite) brings the same business's site back live under the
 * same URL. */
export function deactivateWebsite(businessId: string, tenantId: string): Promise<WebsiteState> {
  return requestJson<WebsiteState>(`/businesses/${businessId}/website/deactivate`, { method: "POST" }, tenantId);
}

// --- Production readiness --------------------------------------------------
//
// GET .../production-readiness (app.routers.businesses) is a read-only
// checklist synthesizing signals this API already exposes elsewhere —
// never a second gate on top of publishing. Only "website_config" and
// "hosting_provider" can ever come back with `blocking: true`; every
// other check (legal profile, custom domain, published) is purely
// informational and Studio must never use it to disable the publish
// action (see ProductionReadinessPanel).

export interface ProductionReadinessCheckResult {
  id: string;
  label: string;
  ready: boolean;
  blocking: boolean;
  detail: string;
}

export interface ProductionReadinessReport {
  checks: ProductionReadinessCheckResult[];
  has_blocking_issues: boolean;
}

export function getProductionReadiness(businessId: string, tenantId: string): Promise<ProductionReadinessReport> {
  return requestJson<ProductionReadinessReport>(
    `/businesses/${businessId}/production-readiness`,
    { method: "GET" },
    tenantId,
  );
}

// --- Website versions + rollback -----------------------------------------
//
// Every successful publish (POST .../website/publish) persists one
// immutable WebsiteVersion snapshot server-side — GET .../website/
// versions reads that history back, most recent first. Rollback (POST
// .../website/versions/{id}/rollback) republishes an old snapshot
// through the exact same publish path a normal publish uses: a failed
// rollback leaves the currently-live site reported live (same
// guarantee a normal failed publish already has), and no version is
// ever deleted, whatever the outcome.

export interface WebsiteVersionSummary {
  id: string;
  published_at: string;
  deploy_url: string;
  is_current: boolean;
}

export function getWebsiteVersions(businessId: string, tenantId: string): Promise<WebsiteVersionSummary[]> {
  return requestJson<WebsiteVersionSummary[]>(`/businesses/${businessId}/website/versions`, { method: "GET" }, tenantId);
}

export function rollbackToWebsiteVersion(
  businessId: string,
  versionId: string,
  tenantId: string,
): Promise<WebsiteState> {
  return requestJson<WebsiteState>(
    `/businesses/${businessId}/website/versions/${versionId}/rollback`,
    { method: "POST" },
    tenantId,
  );
}

// --- Custom domain --------------------------------------------------------
//
// This app never purchases or registers a domain on a business's behalf
// — attachCustomDomain only tells the backend "this domain, which the
// business already owns, should route to its live website" and gets
// back the CNAME target the human must add at their own DNS provider
// (see CustomDomainPanel's own copy, which says this explicitly).
// Attaching requires the website to already be published (live).

export type DomainStatus = "pending_verification" | "active" | "error" | "removed";

export interface CustomDomainState {
  domain: string;
  status: DomainStatus;
  provider_status: string | null;
  cname_target: string | null;
  error_message: string | null;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
}

export function getCustomDomain(businessId: string, tenantId: string): Promise<CustomDomainState | null> {
  return requestJson<CustomDomainState | null>(`/businesses/${businessId}/website/domain`, { method: "GET" }, tenantId);
}

export function attachCustomDomain(businessId: string, domain: string, tenantId: string): Promise<CustomDomainState> {
  return requestJson<CustomDomainState>(
    `/businesses/${businessId}/website/domain`,
    { method: "POST", body: JSON.stringify({ domain }) },
    tenantId,
  );
}

/** Re-checks the hosting provider for real (never a locally-cached
 * guess) — what a human calls after adding the CNAME record attach's
 * response told them to. */
export function refreshCustomDomain(businessId: string, tenantId: string): Promise<CustomDomainState> {
  return requestJson<CustomDomainState>(`/businesses/${businessId}/website/domain/refresh`, { method: "POST" }, tenantId);
}

export function detachCustomDomain(businessId: string, tenantId: string): Promise<CustomDomainState> {
  return requestJson<CustomDomainState>(`/businesses/${businessId}/website/domain`, { method: "DELETE" }, tenantId);
}

// --- Leads --------------------------------------------------------------
//
// GET .../leads (app.routers.businesses) reads persisted Lead rows,
// tenant- and business-scoped server-side (LeadRepository) — most recent
// first. PATCH .../leads/{id}/status is the one write path onto a lead:
// it changes `status` and nothing else (the backend's
// LeadStatusUpdateRequest rejects any other field), same tenant/business
// scoping as the read.

export type LeadStatus = "new" | "contacted" | "qualified" | "won" | "lost";

export interface Lead {
  id: string;
  business_id: string;
  source: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  message: string | null;
  subject: string | null;
  source_url: string | null;
  consent_given: boolean;
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

// --- Creative: brand assets, reviews, strategy/level, generations -------
//
// The Creative Orchestrator layer (apps/api's app.creative +
// app.routers.creative): a business's reusable asset library (Section 2),
// real/imported reviews (Section 4, never fabricated), its creative
// strategy/level (Section 5/12), and its generation history (Section 13).
// Every write here is scoped to one business/tenant exactly like leads
// above — the backend, not this file, is what actually enforces that.

export type AssetKind = "logo" | "image" | "video" | "document";
export type AssetCategory =
  | "logo"
  | "project"
  | "team"
  | "facility"
  | "product"
  | "before"
  | "after"
  | "hero_candidate"
  | "gallery"
  | "other"
  | "low_quality";
export type AssetOrigin = "uploaded" | "imported" | "generated";

export interface BusinessAsset {
  id: string;
  business_id: string;
  kind: AssetKind;
  category: AssetCategory;
  origin: AssetOrigin;
  storage_url: string;
  original_filename: string | null;
  alt_text: string | null;
  generation_id: string | null;
  created_at: string;
}

export interface CreateAssetPayload {
  kind: AssetKind;
  category?: AssetCategory;
  origin: AssetOrigin;
  storage_url: string;
  original_filename?: string | null;
  alt_text?: string | null;
}

export function listBusinessAssets(businessId: string, tenantId: string): Promise<BusinessAsset[]> {
  return requestJson<BusinessAsset[]>(`/businesses/${businessId}/assets`, { method: "GET" }, tenantId);
}

export function createBusinessAsset(
  businessId: string,
  payload: CreateAssetPayload,
  tenantId: string,
): Promise<BusinessAsset> {
  return requestJson<BusinessAsset>(
    `/businesses/${businessId}/assets`,
    { method: "POST", body: JSON.stringify(payload) },
    tenantId,
  );
}

export function updateBusinessAsset(
  businessId: string,
  assetId: string,
  payload: { category?: AssetCategory; alt_text?: string | null },
  tenantId: string,
): Promise<BusinessAsset> {
  return requestJson<BusinessAsset>(
    `/businesses/${businessId}/assets/${assetId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
    tenantId,
  );
}

export function deleteBusinessAsset(businessId: string, assetId: string, tenantId: string): Promise<void> {
  return requestVoid(`/businesses/${businessId}/assets/${assetId}`, { method: "DELETE" }, tenantId);
}

export type ReviewSource = "google" | "manual" | "other";

export interface BusinessReview {
  id: string;
  business_id: string;
  source: ReviewSource;
  source_review_id: string | null;
  author_name: string | null;
  rating: number | null;
  body: string;
  review_url: string | null;
  published_at: string | null;
  imported_at: string;
}

export interface CreateReviewPayload {
  source?: ReviewSource;
  source_review_id?: string | null;
  author_name?: string | null;
  rating?: number | null;
  body: string;
  review_url?: string | null;
  published_at?: string | null;
}

export function listBusinessReviews(businessId: string, tenantId: string): Promise<BusinessReview[]> {
  return requestJson<BusinessReview[]>(`/businesses/${businessId}/reviews`, { method: "GET" }, tenantId);
}

export function createBusinessReview(
  businessId: string,
  payload: CreateReviewPayload,
  tenantId: string,
): Promise<BusinessReview> {
  return requestJson<BusinessReview>(
    `/businesses/${businessId}/reviews`,
    { method: "POST", body: JSON.stringify(payload) },
    tenantId,
  );
}

export function deleteBusinessReview(businessId: string, reviewId: string, tenantId: string): Promise<void> {
  return requestVoid(`/businesses/${businessId}/reviews/${reviewId}`, { method: "DELETE" }, tenantId);
}

// CreativeConfig itself comes from @generate-web-ai/business-config-types
// (generated from apps/api's Pydantic model, same bridge as
// BusinessConfig) — no hand-mirrored shape here to drift from it.

export function getCreativeConfig(businessId: string, tenantId: string): Promise<CreativeConfig> {
  return requestJson<CreativeConfig>(`/businesses/${businessId}/creative-config`, { method: "GET" }, tenantId);
}

export function updateCreativeConfig(
  businessId: string,
  payload: CreativeConfig,
  tenantId: string,
): Promise<CreativeConfig> {
  return requestJson<CreativeConfig>(
    `/businesses/${businessId}/creative-config`,
    { method: "PUT", body: JSON.stringify(payload) },
    tenantId,
  );
}

export type CreativeGenerationType = "website_concept" | "website" | "image" | "video" | "visual_asset";
export type CreativeGenerationStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
export type CreativeProviderName = "internal" | "higgsfield";

export interface CreativeGeneration {
  id: string;
  business_id: string;
  provider: CreativeProviderName;
  generation_type: CreativeGenerationType;
  creative_level: string;
  status: CreativeGenerationStatus;
  external_reference: string | null;
  credits_used: number | null;
  estimated_cost: number | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  created_at: string;
}

export function listCreativeGenerations(businessId: string, tenantId: string): Promise<CreativeGeneration[]> {
  return requestJson<CreativeGeneration[]>(
    `/businesses/${businessId}/creative-generations`,
    { method: "GET" },
    tenantId,
  );
}

/** Triggers one CreativeOrchestrator run (apps/api's
 * app.creative.orchestrator) — generate, regenerate, and "generate a
 * variation" are all this same call (Section 16); the currently
 * published website is never touched by it. Resolves once the provider
 * call has finished (COMPLETED or FAILED) — there is no separate polling
 * step in this phase. */
export function createCreativeGeneration(
  businessId: string,
  generationType: CreativeGenerationType,
  tenantId: string,
): Promise<CreativeGeneration> {
  return requestJson<CreativeGeneration>(
    `/businesses/${businessId}/creative-generations`,
    { method: "POST", body: JSON.stringify({ generation_type: generationType }) },
    tenantId,
  );
}

// --- Real file upload (Phase 3) -----------------------------------------
//
// The counterpart to createBusinessAsset (a URL the caller already has
// hosted somewhere) — this sends an actual file. Deliberately bypasses
// requestJson/sendRequest above: those always set Content-Type:
// application/json, which would break multipart/form-data (the browser
// must set that header itself, boundary included).

export function uploadBusinessAsset(
  businessId: string,
  file: File,
  options: { kind: AssetKind; category?: AssetCategory; altText?: string | null },
  tenantId: string,
): Promise<BusinessAsset> {
  const form = new FormData();
  form.set("file", file);
  form.set("kind", options.kind);
  if (options.category) form.set("category", options.category);
  if (options.altText) form.set("alt_text", options.altText);

  return fetch(`${API_URL}/businesses/${businessId}/assets/upload`, {
    method: "POST",
    headers: { "X-Tenant-Id": tenantId },
    body: form,
  })
    .catch((cause: unknown) => {
      throw new NetworkError(cause);
    })
    .then(async (response) => {
      if (!response.ok) {
        let body: { error?: { code?: string; message?: string; details?: unknown } } = {};
        try {
          body = await response.json();
        } catch {
          // Non-JSON error body — fall through to the generic message.
        }
        throw new ApiError(body.error?.message ?? `Request failed with status ${response.status}.`, {
          code: body.error?.code ?? "http_error",
          status: response.status,
          details: body.error?.details,
        });
      }
      return response.json() as Promise<BusinessAsset>;
    });
}

// --- Creative provider availability (Phase 13) ---------------------------

export interface CreativeProviderAvailability {
  provider: CreativeProviderName;
  available: boolean;
  capabilities: CreativeGenerationType[];
  unavailable_reason: string | null;
}

export function listCreativeProviders(
  businessId: string,
  tenantId: string,
): Promise<CreativeProviderAvailability[]> {
  return requestJson<CreativeProviderAvailability[]>(
    `/businesses/${businessId}/creative-providers`,
    { method: "GET" },
    tenantId,
  );
}

// --- Website drafts: safe generate -> build -> validate -> preview ->
// --- approve -> publish (Phase 6/7/9/10) ----------------------------------
//
// Distinct from WebsiteState above (the currently *published* site) —
// see app.db.models.website_draft.WebsiteDraft's own docstring on the
// backend for why these are two separate models. Publishing a draft
// (publishWebsiteDraft) reuses the exact same publish machinery as
// publishWebsite above; it just requires an APPROVED draft first.

export type WebsiteDraftStatus = "draft" | "building" | "ready" | "build_failed" | "approved" | "published";

export interface WebsiteDraft {
  id: string;
  business_id: string;
  creative_generation_id: string | null;
  site_config: SiteConfig;
  status: WebsiteDraftStatus;
  build_error: string | null;
  validation_issues: string[] | null;
  approved_at: string | null;
  published_at: string | null;
  published_website_id: string | null;
  created_at: string;
}

export function createWebsiteDraft(
  businessId: string,
  siteConfig: SiteConfig,
  creativeGenerationId: string | null,
  tenantId: string,
): Promise<WebsiteDraft> {
  return requestJson<WebsiteDraft>(
    `/businesses/${businessId}/website-drafts`,
    {
      method: "POST",
      body: JSON.stringify({ site_config: siteConfig, creative_generation_id: creativeGenerationId }),
    },
    tenantId,
  );
}

export function listWebsiteDrafts(businessId: string, tenantId: string): Promise<WebsiteDraft[]> {
  return requestJson<WebsiteDraft[]>(`/businesses/${businessId}/website-drafts`, { method: "GET" }, tenantId);
}

export function approveWebsiteDraft(businessId: string, draftId: string, tenantId: string): Promise<WebsiteDraft> {
  return requestJson<WebsiteDraft>(
    `/businesses/${businessId}/website-drafts/${draftId}/approve`,
    { method: "POST" },
    tenantId,
  );
}

/** Requires an APPROVED draft (the backend 409s otherwise) — the one
 * call that actually goes live, reusing the exact same publish machinery
 * publishWebsite above uses. */
export function publishWebsiteDraft(businessId: string, draftId: string, tenantId: string): Promise<WebsiteState> {
  return requestJson<WebsiteState>(
    `/businesses/${businessId}/website-drafts/${draftId}/publish`,
    { method: "POST" },
    tenantId,
  );
}
