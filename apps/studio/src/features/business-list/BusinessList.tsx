import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBanner } from "../business-analysis/ErrorBanner";
import { BUSINESS_VERTICAL_OPTIONS } from "../business-analysis/draft";
import { categorizeDeleteError, type CategorizedError } from "../business-analysis/errors";
import type { BusinessSummary } from "../../lib/api";

interface BusinessListProps {
  businesses: BusinessSummary[];
  /** Deletes the business on the backend (DELETE /businesses/{id}) —
   * the list itself never removes an item; a rejected promise here
   * means nothing changed, and BusinessCard shows the failure inline
   * rather than assuming success. */
  onDelete: (businessId: string) => Promise<void>;
}

const WEBSITE_STATUS_LABEL: Record<NonNullable<BusinessSummary["website"]>["status"], string> = {
  draft: "Not published",
  building: "Publishing…",
  live: "Live",
  failed: "Publish failed",
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
export function BusinessList({ businesses, onDelete }: BusinessListProps) {
  return (
    <ul className="business-list">
      {businesses.map((business) => (
        <BusinessCard key={business.id} business={business} onDelete={onDelete} />
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

function BusinessCard({
  business,
  onDelete,
}: {
  business: BusinessSummary;
  onDelete: (businessId: string) => Promise<void>;
}) {
  const [deleteUi, setDeleteUi] = useState<DeleteUiState>({ kind: "idle" });
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

  const isBusy = deleteUi.kind === "deleting";

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
      </div>

      <div className="business-card__actions">
        <Link className="business-card__open" to={`/businesses/${business.id}`}>
          Open
        </Link>

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
              <button type="button" onClick={() => setDeleteUi({ kind: "idle" })} disabled={isBusy}>
                Cancel
              </button>
              <button type="button" className="button--danger" onClick={handleConfirmDelete} disabled={isBusy}>
                {isBusy ? "Deleting…" : "Confirm delete"}
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
