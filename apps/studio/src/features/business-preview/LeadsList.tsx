import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { Lead, LeadStatus } from "../../lib/api";

interface LeadsListProps {
  leads: Lead[] | null;
  isLoading: boolean;
  error: string | null;
  /** PATCH .../leads/{id}/status (app.routers.businesses), called with
   * the lead being changed and its new status. Resolves with the
   * updated Lead — the caller (PreviewStep) is the one that actually
   * updates `leads`, this component only tracks its own in-flight/error
   * UI state around the call. */
  onUpdateStatus: (leadId: string, status: LeadStatus) => Promise<Lead>;
}

const STATUS_OPTIONS: LeadStatus[] = ["new", "contacted", "qualified", "won", "lost"];
const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  won: "Won",
  lost: "Lost",
};

/** Full message text past this length is collapsed behind "View
 * details" — short enough to skim a list of leads, long enough that
 * most real messages still show in full. */
const MESSAGE_PREVIEW_LENGTH = 140;

function truncateMessage(message: string): { preview: string; isTruncated: boolean } {
  if (message.length <= MESSAGE_PREVIEW_LENGTH) {
    return { preview: message, isTruncated: false };
  }
  return { preview: `${message.slice(0, MESSAGE_PREVIEW_LENGTH).trimEnd()}…`, isTruncated: true };
}

/** List of this business's captured leads, most recent first (the API
 * already orders them — this component never re-sorts). Each lead's
 * status is both shown and changed through the same <select> — no
 * separate display element, keeping this deliberately simple. */
export function LeadsList({ leads, isLoading, error, onUpdateStatus }: LeadsListProps) {
  const [pendingLeadId, setPendingLeadId] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [expandedLeadIds, setExpandedLeadIds] = useState<Set<string>>(new Set());

  function toggleExpanded(leadId: string) {
    setExpandedLeadIds((current) => {
      const next = new Set(current);
      if (next.has(leadId)) {
        next.delete(leadId);
      } else {
        next.add(leadId);
      }
      return next;
    });
  }

  if (isLoading) {
    return <p>Loading leads…</p>;
  }

  if (error) {
    return <p className="banner banner--error">Could not load leads: {error}</p>;
  }

  if (!leads || leads.length === 0) {
    return <p className="field-hint">No leads captured yet for this business.</p>;
  }

  async function handleStatusChange(leadId: string, status: LeadStatus) {
    setPendingLeadId(leadId);
    setStatusError(null);
    try {
      await onUpdateStatus(leadId, status);
    } catch (caught) {
      setStatusError(friendlyErrorMessage(caught, "Could not update lead status."));
    } finally {
      setPendingLeadId(null);
    }
  }

  return (
    <>
      {statusError && <p className="banner banner--error">{statusError}</p>}
      <ul className="leads-list">
        {leads.map((lead) => {
          const isExpanded = expandedLeadIds.has(lead.id);
          const { preview, isTruncated } = lead.message ? truncateMessage(lead.message) : { preview: "", isTruncated: false };
          const hasDetails = isTruncated || lead.subject || lead.source_url;

          return (
            <li className="leads-list__item" key={lead.id}>
              <div className="leads-list__row">
                <span className="leads-list__name">{lead.name ?? "(no name)"}</span>
                <span className="leads-list__date">{new Date(lead.created_at).toLocaleString()}</span>
              </div>
              <div className="leads-list__contact">
                {lead.email && <span>{lead.email}</span>}
                {lead.phone && <span>{lead.phone}</span>}
                {!lead.email && !lead.phone && <span className="field-hint">No contact details captured.</span>}
                <span className="field-hint">Source: {lead.source}</span>
              </div>
              {isExpanded && lead.subject && (
                <p className="leads-list__message">
                  <strong>Subject:</strong> {lead.subject}
                </p>
              )}
              {lead.message && <p className="leads-list__message">{isExpanded ? lead.message : preview}</p>}
              {isExpanded && lead.source_url && (
                <p className="field-hint">
                  Submitted from:{" "}
                  <a href={lead.source_url} target="_blank" rel="noreferrer">
                    {lead.source_url}
                  </a>
                </p>
              )}
              {isExpanded && (
                <p className="field-hint">{lead.consent_given ? "Consent given at submission." : "No consent recorded."}</p>
              )}
              {hasDetails && (
                <button type="button" onClick={() => toggleExpanded(lead.id)}>
                  {isExpanded ? "Hide details" : "View details"}
                </button>
              )}
              <div className="leads-list__status">
                <label>
                  Status:{" "}
                  <select
                    value={lead.status}
                    disabled={pendingLeadId === lead.id}
                    onChange={(event) => handleStatusChange(lead.id, event.target.value as LeadStatus)}
                  >
                    {STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>
                        {STATUS_LABELS[status]}
                      </option>
                    ))}
                  </select>
                </label>
                {pendingLeadId === lead.id && <span className="field-hint"> Saving…</span>}
              </div>
            </li>
          );
        })}
      </ul>
    </>
  );
}
