import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBanner } from "../business-analysis/ErrorBanner";
import { BUSINESS_VERTICAL_OPTIONS } from "../business-analysis/draft";
import {
  categorizeActivationError,
  categorizeDeleteError,
  categorizeWebsiteDeactivateError,
  type CategorizedError,
} from "../business-analysis/errors";
import type { AutomationState, BusinessSummary, WebsiteState } from "../../lib/api";

interface BusinessListProps {
  businesses: BusinessSummary[];
  /** Deletes the business on the backend (DELETE /businesses/{id}) —
   * the list itself never removes an item; a rejected promise here
   * means nothing changed, and BusinessCard shows the failure inline
   * rather than assuming success. */
  onDelete: (businessId: string) => Promise<void>;
  /** Takes this business's live website down for real on the hosting
   * provider (POST .../website/deactivate) — resolves to the backend's
   * new persisted WebsiteState so the card can reflect it without a
   * full reload. */
  onDeactivateWebsite: (businessId: string) => Promise<WebsiteState>;
  /** Deactivates this business's active n8n automation (POST
   * .../automation/deactivate) — the same action PreviewStep's own
   * Deactivate button already uses. Resolves to the backend's new
   * persisted AutomationState. */
  onDeactivateAutomation: (businessId: string) => Promise<AutomationState>;
}

const WEBSITE_STATUS_LABEL: Record<NonNullable<BusinessSummary["website"]>["status"], string> = {
  draft: "Not published",
  building: "Publishing…",
  live: "Live",
  failed: "Publish failed",
  inactive: "Deactivated",
};

const AUTOMATION_STATUS_LABEL: Record<NonNullable<BusinessSummary["automation"]>["status"], string> = {
  draft: "Not activated",
  provisioning: "Activating…",
  active: "Active",
  inactive: "Inactive",
  error: "Error",
};

function verticalLabel(vertical: BusinessSummary["vertical"]): string {
  return BUSINESS_VERTICAL_OPTIONS.find((option) => option.value === vertical)?.label ?? vertical;
}

function locationLabel(business: BusinessSummary): string | null {
  if (!business.location) return null;
  return [business.location.city, business.location.region, business.location.country].filter(Boolean).join(", ");
}

/** Studio's home-screen listing — every business the current tenant
 * owns, each showing enough to decide whether to reopen it (name,
 * location/vertical, business/website/automation status) without
 * showing or duplicating its full BusinessConfig. Website and
 * automation status come straight from the backend's
 * GET /business-summaries (see lib/api's BusinessSummary docstring) —
 * never inferred from config here. */
export function BusinessList({ businesses, onDelete, onDeactivateWebsite, onDeactivateAutomation }: BusinessListProps) {
  return (
    <ul className="business-list">
      {businesses.map((business) => (
        <BusinessCard
          key={business.id}
          business={business}
          onDelete={onDelete}
          onDeactivateWebsite={onDeactivateWebsite}
          onDeactivateAutomation={onDeactivateAutomation}
        />
      ))}
    </ul>
  );
}

// Local, ephemeral UI feedback only — never the source of truth for
// whether the business still exists (once onDelete resolves, the
// parent's own list no longer includes this business at all, so this
// card simply unmounts; there's no "deleted" state to render here).
// "confirming" is the pre-delete confirmation step; "deleting" covers
// the in-flight request; "failed" is the last attempt's outcome,
// cleared as soon as another attempt starts.
type DeleteUiState =
  | { kind: "idle" }
  | { kind: "confirming" }
  | { kind: "deleting" }
  | { kind: "failed"; error: CategorizedError };

// Same local-feedback-only role as DeleteUiState above, for the two
// single-click deactivate actions — no confirmation step, matching
// PreviewStep's own WorkflowPreview "Deactivate" button (only
// *activating* something gets a confirm step in this codebase; turning
// something off does not).
type DeactivateUiState = { kind: "idle" } | { kind: "busy" } | { kind: "failed"; error: CategorizedError };

function BusinessCard({
  business,
  onDelete,
  onDeactivateWebsite,
  onDeactivateAutomation,
}: {
  business: BusinessSummary;
  onDelete: (businessId: string) => Promise<void>;
  onDeactivateWebsite: (businessId: string) => Promise<WebsiteState>;
  onDeactivateAutomation: (businessId: string) => Promise<AutomationState>;
}) {
  const [deleteUi, setDeleteUi] = useState<DeleteUiState>({ kind: "idle" });
  const [websiteUi, setWebsiteUi] = useState<DeactivateUiState>({ kind: "idle" });
  const [automationUi, setAutomationUi] = useState<DeactivateUiState>({ kind: "idle" });
  const location = locationLabel(business);

  async function handleConfirmDelete() {
    setDeleteUi({ kind: "deleting" });
    try {
      await onDelete(business.id);
      // Success: the parent's list no longer includes this business,
      // so this component unmounts — nothing left to set here.
    } catch (caught) {
      setDeleteUi({ kind: "failed", error: categorizeDeleteError(caught) });
    }
  }

  async function handleDeactivateWebsite() {
    setWebsiteUi({ kind: "busy" });
    try {
      await onDeactivateWebsite(business.id);
      setWebsiteUi({ kind: "idle" });
    } catch (caught) {
      setWebsiteUi({ kind: "failed", error: categorizeWebsiteDeactivateError(caught) });
    }
  }

  async function handleDeactivateAutomation() {
    setAutomationUi({ kind: "busy" });
    try {
      await onDeactivateAutomation(business.id);
      setAutomationUi({ kind: "idle" });
    } catch (caught) {
      setAutomationUi({ kind: "failed", error: categorizeActivationError(caught) });
    }
  }

  const isDeleting = deleteUi.kind === "deleting";

  return (
    <li className="business-card">
      <div className="business-card__main">
        <h3 className="business-card__name">{business.name}</h3>
        <p className="business-card__meta">
          {verticalLabel(business.vertical)}
          {location ? ` · ${location}` : ""}
        </p>
        <dl className="business-card__status">
          <div className="business-card__status-item">
            <dt>Business</dt>
            <dd>{business.status}</dd>
          </div>
          <div className="business-card__status-item">
            <dt>Website</dt>
            <dd>{business.website ? WEBSITE_STATUS_LABEL[business.website.status] : "Not published"}</dd>
          </div>
          <div className="business-card__status-item">
            <dt>Automation</dt>
            <dd>{business.automation ? AUTOMATION_STATUS_LABEL[business.automation.status] : "Not activated"}</dd>
          </div>
        </dl>

        {websiteUi.kind === "failed" && <ErrorBanner error={websiteUi.error} />}
        {automationUi.kind === "failed" && <ErrorBanner error={automationUi.error} />}
      </div>

      <div className="business-card__actions">
        <Link className="business-card__open" to={`/businesses/${business.id}`}>
          Open
        </Link>

        {business.website?.status === "live" && (
          <button type="button" onClick={handleDeactivateWebsite} disabled={websiteUi.kind === "busy"}>
            {websiteUi.kind === "busy" ? "Deactivating…" : "Deactivate website"}
          </button>
        )}

        {business.automation?.active && (
          <button type="button" onClick={handleDeactivateAutomation} disabled={automationUi.kind === "busy"}>
            {automationUi.kind === "busy" ? "Deactivating…" : "Deactivate automation"}
          </button>
        )}

        {deleteUi.kind === "idle" && (
          <button type="button" className="button--danger" onClick={() => setDeleteUi({ kind: "confirming" })}>
            Delete
          </button>
        )}

        {(deleteUi.kind === "confirming" || deleteUi.kind === "deleting") && (
          <div className="business-card__delete-confirm">
            <p className="banner__title">Delete "{business.name}"?</p>
            <p className="activation-confirm__warning">
              This permanently removes this business, its website, its automation, and its leads. This cannot be
              undone.
            </p>
            <div className="proposal-actions">
              <button type="button" onClick={() => setDeleteUi({ kind: "idle" })} disabled={isDeleting}>
                Cancel
              </button>
              <button type="button" className="button--danger" onClick={handleConfirmDelete} disabled={isDeleting}>
                {isDeleting ? "Deleting…" : "Confirm delete"}
              </button>
            </div>
          </div>
        )}

        {deleteUi.kind === "failed" && (
          <div className="business-card__delete-confirm">
            <ErrorBanner error={deleteUi.error} />
            <div className="proposal-actions">
              <button type="button" onClick={() => setDeleteUi({ kind: "idle" })}>
                Cancel
              </button>
              <button type="button" className="button--danger" onClick={handleConfirmDelete}>
                Try again
              </button>
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
