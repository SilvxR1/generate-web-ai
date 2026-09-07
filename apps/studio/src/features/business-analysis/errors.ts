import { ApiError, NetworkError } from "../../lib/api";

/**
 * Four distinct failure shapes the onboarding flow can hit, each with
 * its own human message — never a raw stack trace or bare JSON as the
 * primary message:
 *
 * - "ai_unavailable": the analyzer itself couldn't be reached (not
 *   configured server-side, or the LLM provider request failed).
 * - "analysis_failed": the analyzer ran but produced nothing usable
 *   (a refusal, malformed output) — the briefing itself may need work.
 * - "invalid_proposal": the reviewed draft has a problem a human needs
 *   to fix before it can be saved (client-side validation, or the
 *   backend's own 422/409 on create).
 * - "api_failure": anything else — network down, unknown tenant,
 *   unexpected 5xx.
 * - "activation_failed": activating automation didn't succeed — missing
 *   n8n configuration/credentials, an unsupported capability, or the
 *   n8n call itself failing. Never shown as "Active" when this fires.
 * - "publish_failed": publishing the website didn't succeed — missing
 *   hosting-provider configuration, or the provider call itself
 *   failing. Never shown as "Published" when this fires.
 * - "delete_failed": deleting a business didn't succeed — the backend
 *   couldn't safely deactivate its active remote automation first, or
 *   the delete call itself failed. Never shown as removed from the
 *   dashboard when this fires.
 */
export type ErrorCategory =
  | "ai_unavailable"
  | "analysis_failed"
  | "invalid_proposal"
  | "api_failure"
  | "activation_failed"
  | "publish_failed"
  | "delete_failed";

export interface CategorizedError {
  category: ErrorCategory;
  title: string;
  message: string;
  /** Raw code/status, shown only in a collapsed technical detail — never as the headline. */
  technicalDetail?: string;
}

const NETWORK_ERROR: CategorizedError = {
  category: "api_failure",
  title: "Can't reach the server",
  message: "The Studio backend didn't respond. Check that it's running and reachable, then try again.",
};

export function categorizeAnalyzeError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return NETWORK_ERROR;
  }
  if (error instanceof ApiError) {
    if (error.code === "business_analyzer_not_configured" || error.code === "analyzer_provider_error") {
      return {
        category: "ai_unavailable",
        title: "AI analyzer unavailable",
        message: "The AI Business Analyzer isn't reachable right now. Try again shortly.",
        technicalDetail: `${error.code} (${error.status})`,
      };
    }
    if (error.code === "invalid_analysis_output") {
      return {
        category: "analysis_failed",
        title: "Analysis failed",
        message: "The AI couldn't produce a usable proposal from this briefing. Try rephrasing it with more concrete details.",
        technicalDetail: `${error.code} (${error.status})`,
      };
    }
    return {
      category: "api_failure",
      title: "Request failed",
      message: error.message,
      technicalDetail: `${error.code} (${error.status})`,
    };
  }
  return { category: "api_failure", title: "Unexpected error", message: toMessage(error) };
}

/** Used for both POST /businesses (create) and PUT /businesses/{id}
 * (the "Edit business" path from the preview step) — same backend
 * validation, same failure shapes either way. */
export function categorizeSaveError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return NETWORK_ERROR;
  }
  if (error instanceof ApiError) {
    if (error.code === "validation_error") {
      return {
        category: "invalid_proposal",
        title: "Proposal needs a fix",
        message: "The backend rejected some of these fields. Check the values below and try again.",
        technicalDetail: JSON.stringify(error.details ?? error.message),
      };
    }
    if (error.code === "slug_conflict") {
      return {
        category: "invalid_proposal",
        title: "Slug already in use",
        message: "That slug belongs to another business already. Change it and try again.",
        technicalDetail: `${error.code} (${error.status})`,
      };
    }
    return genericApiFailure(error, "Could not save this business");
  }
  return { category: "api_failure", title: "Unexpected error", message: toMessage(error) };
}

/** The workflow preview has no special-cased failure codes of its own
 * (it's a plain read) — any error here is just "the request failed". */
export function categorizeWorkflowPreviewError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return NETWORK_ERROR;
  }
  if (error instanceof ApiError) {
    return genericApiFailure(error, "Could not load the automation preview");
  }
  return { category: "api_failure", title: "Unexpected error", message: toMessage(error) };
}

/** Used for both the dashboard's GET /business-summaries listing and
 * reopening a single business (GET /businesses/{id}) — plain reads with
 * no special-cased failure codes of their own, same shape as
 * categorizeWorkflowPreviewError above. */
export function categorizeBusinessFetchError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return NETWORK_ERROR;
  }
  if (error instanceof ApiError) {
    return genericApiFailure(error, "Could not load this business");
  }
  return { category: "api_failure", title: "Unexpected error", message: toMessage(error) };
}

const ACTIVATION_ERROR_TITLES: Record<string, string> = {
  n8n_not_configured: "Automation isn't set up on this server",
  missing_capability_configuration: "Missing required configuration",
  unsupported_capability: "Unsupported automation",
  automation_not_enabled: "Automation not enabled",
  no_business_config: "Nothing to activate",
  automation_activation_failed: "Activation failed",
  automation_deactivation_failed: "Deactivation failed",
  automation_not_activated: "Nothing to deactivate",
};

/** Never returns anything implying success — every branch here means
 * activation did NOT happen. */
export function categorizeActivationError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return { ...NETWORK_ERROR, category: "activation_failed" };
  }
  if (error instanceof ApiError) {
    return {
      category: "activation_failed",
      title: ACTIVATION_ERROR_TITLES[error.code] ?? "Could not activate automation",
      message: error.message,
      technicalDetail: `${error.code} (${error.status})`,
    };
  }
  return { category: "activation_failed", title: "Unexpected error", message: toMessage(error) };
}

const PUBLISH_ERROR_TITLES: Record<string, string> = {
  website_publisher_not_configured: "Publishing isn't set up on this server",
  website_publish_failed: "Publishing failed",
};

/** Never returns anything implying success — every branch here means
 * publishing did NOT happen. */
export function categorizePublishError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return { ...NETWORK_ERROR, category: "publish_failed" };
  }
  if (error instanceof ApiError) {
    return {
      category: "publish_failed",
      title: PUBLISH_ERROR_TITLES[error.code] ?? "Could not publish this website",
      message: error.message,
      technicalDetail: `${error.code} (${error.status})`,
    };
  }
  return { category: "publish_failed", title: "Unexpected error", message: toMessage(error) };
}

const DELETE_ERROR_TITLES: Record<string, string> = {
  business_not_found: "Business not found",
  n8n_not_configured: "Can't safely delete — automation isn't set up on this server",
  automation_deactivation_failed: "Can't safely delete — deactivating automation failed",
};

/** Never returns anything implying success — every branch here means
 * deletion did NOT happen (see DELETE /businesses/{id}'s own docstring,
 * apps/api's app.routers.businesses, for why a business with an active
 * remote automation is refused rather than silently orphaning it). */
export function categorizeDeleteError(error: unknown): CategorizedError {
  if (error instanceof NetworkError) {
    return { ...NETWORK_ERROR, category: "delete_failed" };
  }
  if (error instanceof ApiError) {
    return {
      category: "delete_failed",
      title: DELETE_ERROR_TITLES[error.code] ?? "Could not delete this business",
      message: error.message,
      technicalDetail: `${error.code} (${error.status})`,
    };
  }
  return { category: "delete_failed", title: "Unexpected error", message: toMessage(error) };
}

function genericApiFailure(error: ApiError, title: string): CategorizedError {
  return {
    category: "api_failure",
    title,
    message: error.message,
    technicalDetail: `${error.code} (${error.status})`,
  };
}

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong.";
}

/** For the few call sites that show a bare string rather than a full
 * ErrorBanner (e.g. an inline "Could not load leads: …") — still routes
 * a NetworkError to the same friendly copy as everywhere else, instead
 * of leaking a raw browser message like "Failed to fetch". An ApiError's
 * own `.message` is already human-readable (apps/api's error contract),
 * so it's used as-is. */
export function friendlyErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof NetworkError) {
    return NETWORK_ERROR.message;
  }
  if (error instanceof ApiError) {
    return error.message;
  }
  return error instanceof Error ? error.message : fallback;
}
