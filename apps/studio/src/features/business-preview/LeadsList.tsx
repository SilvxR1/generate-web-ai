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

const STATUS_OPTIONS: LeadStatus[] = ["new", "contacted", "won", "lost"];
const STATUS_LABELS: Record<LeadStatus, string> = { new: "New", contacted: "Contacted", won: "Won", lost: "Lost" };

/** List of this business's captured leads, most recent first (the API
 * already orders them — this component never re-sorts). Each lead's
 * status is both shown and changed through the same <select> — no
 * separate display element, keeping this deliberately simple. */
export function LeadsList({ leads, isLoading, error, onUpdateStatus }: LeadsListProps) {
  const [pendingLeadId, setPendingLeadId] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

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
        {leads.map((lead) => (
          <li className="leads-list__item" key={lead.id}>
            <div className="leads-list__row">
              <span className="leads-list__name">{lead.name ?? "(no name)"}</span>
              <span className="leads-list__date">{new Date(lead.created_at).toLocaleString()}</span>
            </div>
            <div className="leads-list__contact">
              {lead.email && <span>{lead.email}</span>}
              {lead.phone && <span>{lead.phone}</span>}
              {!lead.email && !lead.phone && <span className="field-hint">No contact details captured.</span>}
            </div>
            {lead.message && <p className="leads-list__message">{lead.message}</p>}
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
        ))}
      </ul>
    </>
  );
}
