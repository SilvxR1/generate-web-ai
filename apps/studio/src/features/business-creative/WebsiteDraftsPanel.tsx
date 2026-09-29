import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import { RealPreviewAction } from "../business-preview/RealPreviewAction";
import { CONTENT_SUMMARY_HINT, REAL_PREVIEW_NOTICE } from "../business-preview/realPreview";
import { SiteConfigPreview } from "../business-preview/SiteConfigPreview";
import type { WebsiteDraft, WebsiteDraftPreview, WebsiteState } from "../../lib/api";

interface WebsiteDraftsPanelProps {
  drafts: WebsiteDraft[] | null;
  isLoading: boolean;
  error: string | null;
  /** POST .../website-drafts/{id}/approve — the explicit human action
   * between preview and publish (Phase 10). Never publishes by itself. */
  onApprove: (draftId: string) => Promise<WebsiteDraft>;
  /** POST .../website-drafts/{id}/preview (A8.3.4.2b) — the draft's REAL
   * built website, opened in a new tab. Never approves or publishes. */
  onPreview: (draftId: string) => Promise<WebsiteDraftPreview>;
  /** POST .../website-drafts/{id}/publish — requires an APPROVED draft;
   * reuses the exact same publish machinery WebsitePublish (above, in
   * business-preview) uses. */
  onPublish: (draftId: string) => Promise<WebsiteState>;
}

function isPreviewable(draft: WebsiteDraft): boolean {
  return draft.status === "ready" || draft.status === "approved";
}

const STATUS_LABELS: Record<WebsiteDraft["status"], string> = {
  draft: "Draft",
  building: "Building…",
  ready: "Ready to review",
  build_failed: "Build failed",
  approved: "Approved — ready to publish",
  published: "Published",
};

/** Generated proposals, distinct from the currently *published* website
 * (Phase 9) — WebsitePublish (business-preview) shows that; this shows
 * every DETERMINISTIC draft ever generated (see GenerativeWorkflowPanel
 * for the separate AI Frontend Engineer track — P2 continuation Part 5
 * deliberately keeps the two apart, never mixed in one list), most
 * recent first, with the explicit Approve -> Publish actions Phase 10
 * requires. A8.3.4.2b: READY/APPROVED drafts offer "Open real preview"
 * (the exact built website); the React SiteConfigPreview is only a
 * secondary "Content summary", never labeled a preview. */
export function WebsiteDraftsPanel({
  drafts: allDrafts,
  isLoading,
  error,
  onApprove,
  onPreview,
  onPublish,
}: WebsiteDraftsPanelProps) {
  const drafts = (allDrafts ?? []).filter((draft) => draft.engine === "deterministic");
  const [openDraftId, setOpenDraftId] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleApprove(draftId: string) {
    setPendingId(draftId);
    setActionError(null);
    try {
      await onApprove(draftId);
    } catch (caught) {
      setActionError(friendlyErrorMessage(caught, "Could not approve this draft."));
    } finally {
      setPendingId(null);
    }
  }

  async function handlePublish(draftId: string) {
    setPendingId(draftId);
    setActionError(null);
    try {
      await onPublish(draftId);
    } catch (caught) {
      setActionError(friendlyErrorMessage(caught, "Could not publish this draft."));
    } finally {
      setPendingId(null);
    }
  }

  if (isLoading) {
    return <p className="field-hint">Loading generated proposals…</p>;
  }
  if (error) {
    return <p className="banner banner--error">Could not load generated proposals: {error}</p>;
  }
  if (drafts.length === 0) {
    return <p className="field-hint">No generated proposal yet — click "Generate website" above to create one.</p>;
  }

  return (
    <div className="website-drafts-panel">
      {actionError && <p className="banner banner--error">{actionError}</p>}
      {drafts.some(isPreviewable) && <p className="field-hint real-preview__notice">{REAL_PREVIEW_NOTICE}</p>}
      <ul className="website-drafts-panel__list">
        {drafts.map((draft) => (
          <li key={draft.id} className="website-drafts-panel__item">
            <div className="website-drafts-panel__row">
              <strong>{STATUS_LABELS[draft.status]}</strong>
              <span className="field-hint">{new Date(draft.created_at).toLocaleString()}</span>
            </div>

            {draft.build_error && <p className="banner banner--error">Build failed: {draft.build_error}</p>}
            {draft.validation_issues && draft.validation_issues.length > 0 && (
              <ul className="website-drafts-panel__issues">
                {draft.validation_issues.map((issue) => (
                  <li key={issue} className="field-hint">
                    ⚠ {issue}
                  </li>
                ))}
              </ul>
            )}

            <div className="website-drafts-panel__actions">
              {isPreviewable(draft) && (
                <RealPreviewAction requestPreview={() => onPreview(draft.id)} showNotice={false} />
              )}
              {draft.site_config && (
                <button
                  type="button"
                  aria-expanded={openDraftId === draft.id}
                  onClick={() => setOpenDraftId(openDraftId === draft.id ? null : draft.id)}
                >
                  {openDraftId === draft.id ? "Hide content summary" : "Content summary"}
                </button>
              )}
              {draft.status === "ready" && (
                <button type="button" onClick={() => handleApprove(draft.id)} disabled={pendingId === draft.id}>
                  {pendingId === draft.id ? "Approving…" : "Approve"}
                </button>
              )}
              {draft.status === "approved" && (
                <button type="button" onClick={() => handlePublish(draft.id)} disabled={pendingId === draft.id}>
                  {pendingId === draft.id ? "Publishing…" : "Publish"}
                </button>
              )}
              {draft.status === "published" && <span className="field-hint">Published from this draft.</span>}
            </div>

            {openDraftId === draft.id && draft.site_config && (
              <div className="content-summary">
                <p className="field-hint">{CONTENT_SUMMARY_HINT}</p>
                <SiteConfigPreview siteConfig={draft.site_config} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
