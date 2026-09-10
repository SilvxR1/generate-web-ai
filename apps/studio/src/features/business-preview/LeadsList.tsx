import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import { createLeadNote, getLeadNotes, type Lead, type LeadFilters, type LeadNote, type LeadStatus } from "../../lib/api";

interface LeadsListProps {
  leads: Lead[] | null;
  isLoading: boolean;
  error: string | null;
  businessId: string;
  tenantId: string;
  filters: LeadFilters;
  onFiltersChange: (filters: LeadFilters) => void;
  /** PATCH .../leads/{id}/status (app.routers.businesses), called with
   * the lead being changed and its new status. Resolves with the
   * updated Lead — the caller (PreviewStep) is the one that actually
   * updates `leads`, this component only tracks its own in-flight/error
   * UI state around the call. */
  onUpdateStatus: (leadId: string, status: LeadStatus) => Promise<Lead>;
}

const SOURCE_LABELS: Record<string, string> = {
  website_form: "Website form",
  email: "Email",
  phone: "Phone",
  whatsapp: "WhatsApp",
  manual: "Manual",
  other: "Other",
};

const ACKNOWLEDGEMENT_LABELS: Record<Lead["acknowledgement_status"], string> = {
  sent: "Confirmation sent",
  pending: "Confirmation pending",
  failed: "Confirmation failed",
  not_configured: "Confirmation email not configured",
};

function whatsappHref(phone: string): string {
  return `https://wa.me/${phone.replace(/\D/g, "")}`;
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
export function LeadsList({
  leads,
  isLoading,
  error,
  businessId,
  tenantId,
  filters,
  onFiltersChange,
  onUpdateStatus,
}: LeadsListProps) {
  const [pendingLeadId, setPendingLeadId] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [expandedLeadIds, setExpandedLeadIds] = useState<Set<string>>(new Set());
  const [searchInput, setSearchInput] = useState(filters.search ?? "");

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

  const filterBar = (
    <form
      className="leads-list__filters"
      onSubmit={(event) => {
        event.preventDefault();
        onFiltersChange({ ...filters, search: searchInput.trim() || undefined });
      }}
    >
      <input
        type="search"
        placeholder="Search name, email, phone, message…"
        value={searchInput}
        onChange={(event) => setSearchInput(event.target.value)}
      />
      <label>
        Filter by status:{" "}
        <select
          value={filters.status ?? ""}
          onChange={(event) =>
            onFiltersChange({ ...filters, status: (event.target.value || undefined) as LeadStatus | undefined })
          }
        >
          <option value="">All</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABELS[status]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Filter by source:{" "}
        <select
          value={filters.source ?? ""}
          onChange={(event) => onFiltersChange({ ...filters, source: event.target.value || undefined })}
        >
          <option value="">All</option>
          {Object.entries(SOURCE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Search</button>
    </form>
  );

  if (isLoading) {
    return (
      <>
        {filterBar}
        <p>Loading leads…</p>
      </>
    );
  }

  if (error) {
    return (
      <>
        {filterBar}
        <p className="banner banner--error">Could not load leads: {error}</p>
      </>
    );
  }

  if (!leads || leads.length === 0) {
    const hasActiveFilters = Boolean(filters.search || filters.status || filters.source);
    return (
      <>
        {filterBar}
        <p className="field-hint">
          {hasActiveFilters ? "No leads match these filters." : "No leads captured yet for this business."}
        </p>
      </>
    );
  }

  return (
    <>
      {filterBar}
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
                {lead.email && (
                  <span>
                    {lead.email} <a href={`mailto:${lead.email}`}>Email</a>
                  </span>
                )}
                {lead.phone && (
                  <span>
                    {lead.phone} <a href={`tel:${lead.phone}`}>Call</a>{" "}
                    <a href={whatsappHref(lead.phone)} target="_blank" rel="noreferrer">
                      WhatsApp
                    </a>
                  </span>
                )}
                {!lead.email && !lead.phone && <span className="field-hint">No contact details captured.</span>}
                <span className="field-hint">Source: {SOURCE_LABELS[lead.source] ?? lead.source}</span>
                <span className="field-hint">{ACKNOWLEDGEMENT_LABELS[lead.acknowledgement_status]}</span>
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
              <LeadNotes businessId={businessId} leadId={lead.id} tenantId={tenantId} />
            </li>
          );
        })}
      </ul>
    </>
  );
}

interface LeadNotesProps {
  businessId: string;
  leadId: string;
  tenantId: string;
}

/** Simple internal notes on one lead (P1.3) — not a CRM activity
 * timeline: one flat, oldest-first list, fetched only once expanded. */
function LeadNotes({ businessId, leadId, tenantId }: LeadNotesProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [notes, setNotes] = useState<LeadNote[] | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [draft, setDraft] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    setIsOpen(true);
    if (notes !== null) return;
    setIsLoading(true);
    try {
      setNotes(await getLeadNotes(businessId, leadId, tenantId));
    } catch (caught) {
      setError(friendlyErrorMessage(caught, "Could not load notes."));
    } finally {
      setIsLoading(false);
    }
  }

  async function handleAddNote(event: React.FormEvent) {
    event.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setIsSaving(true);
    setError(null);
    try {
      const note = await createLeadNote(businessId, leadId, body, tenantId);
      setNotes((current) => [...(current ?? []), note]);
      setDraft("");
    } catch (caught) {
      setError(friendlyErrorMessage(caught, "Could not save this note."));
    } finally {
      setIsSaving(false);
    }
  }

  if (!isOpen) {
    return (
      <button type="button" onClick={open}>
        Notes
      </button>
    );
  }

  return (
    <div className="leads-list__notes">
      {isLoading && <p className="field-hint">Loading notes…</p>}
      {error && <p className="banner banner--error">{error}</p>}
      {notes && notes.length > 0 && (
        <ul>
          {notes.map((note) => (
            <li key={note.id}>
              <span className="field-hint">{new Date(note.created_at).toLocaleString()}</span> {note.body}
            </li>
          ))}
        </ul>
      )}
      {notes && notes.length === 0 && <p className="field-hint">No notes yet.</p>}
      <form onSubmit={handleAddNote}>
        <input
          type="text"
          placeholder="Add a note…"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={isSaving}
        />
        <button type="submit" disabled={isSaving || draft.trim() === ""}>
          {isSaving ? "Saving…" : "Add note"}
        </button>
      </form>
    </div>
  );
}
