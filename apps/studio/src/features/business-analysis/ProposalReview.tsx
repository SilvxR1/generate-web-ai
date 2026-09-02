import { AutomationRecommendationAction } from "./AutomationRecommendationAction";
import type { AnalyzeBusinessResponse } from "../../lib/api";
import { ErrorBanner } from "./ErrorBanner";
import type { CategorizedError } from "./errors";
import { BUSINESS_VERTICAL_OPTIONS, LEAD_SOURCE_OPTIONS, type BusinessDraft, nextServiceDraftKey, slugify } from "./draft";

type DraftUpdater = (updater: (prev: BusinessDraft) => BusinessDraft) => void;

interface ProposalReviewProps {
  analysis: AnalyzeBusinessResponse;
  draft: BusinessDraft;
  onChange: DraftUpdater;
  tenantId: string;
  /** true when reached via the preview step's "Edit business" on an
   * already-persisted business, false for a brand-new proposal fresh
   * off an /analyze call. Controls only whether the recommended-
   * automation summary shows itself automatically (see
   * AutomationRecommendationAction's `autoShow`) — never anything about
   * automation.* itself, which always comes from `draft`. */
  isEditingExisting: boolean;
  onBack: () => void;
  onCreate: () => void;
  isCreating: boolean;
  createError: CategorizedError | null;
  /** "Create business" (default) when this is a brand-new business, or
   * "Save changes" when reached via the preview step's "Edit business". */
  submitLabel?: string;
}

export function ProposalReview({
  analysis,
  draft,
  onChange,
  tenantId,
  isEditingExisting,
  onBack,
  onCreate,
  isCreating,
  createError,
  submitLabel = "Create business",
}: ProposalReviewProps) {
  const hasProposal = analysis.proposed_config !== null;

  return (
    <div className="proposal-review">
      {!hasProposal && (
        <p className="banner banner--warning">
          The AI couldn't propose a full configuration from this briefing. Fill in the fields below yourself — the
          questions below explain what was missing.
        </p>
      )}

      {(analysis.missing_information.length > 0 || analysis.questions.length > 0) && (
        <div className="callout">
          {analysis.missing_information.length > 0 && (
            <>
              <p className="callout__title">Missing information</p>
              <ul>
                {analysis.missing_information.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </>
          )}
          {analysis.questions.length > 0 && (
            <>
              <p className="callout__title">Questions to consider</p>
              <ul>
                {analysis.questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      <fieldset className="form-section">
        <legend>Basics</legend>

        <label className="field-label" htmlFor="business-name">
          Name
        </label>
        <input
          id="business-name"
          type="text"
          value={draft.name}
          onChange={(event) => {
            const name = event.target.value;
            onChange((prev) => ({ ...prev, name, slug: prev.slugTouched ? prev.slug : slugify(name) }));
          }}
        />

        <label className="field-label" htmlFor="business-slug">
          Slug
        </label>
        <input
          id="business-slug"
          type="text"
          value={draft.slug}
          onChange={(event) => {
            const slug = event.target.value;
            onChange((prev) => ({ ...prev, slug, slugTouched: true }));
          }}
        />

        <label className="field-label" htmlFor="business-vertical">
          Sector
        </label>
        <select
          id="business-vertical"
          value={draft.vertical}
          onChange={(event) => {
            const vertical = event.target.value as BusinessDraft["vertical"];
            onChange((prev) => ({ ...prev, vertical }));
          }}
        >
          {BUSINESS_VERTICAL_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>

        <label className="field-label" htmlFor="business-description">
          Description
        </label>
        <textarea
          id="business-description"
          rows={3}
          value={draft.description}
          onChange={(event) => {
            const description = event.target.value;
            onChange((prev) => ({ ...prev, description }));
          }}
        />

        <label className="field-label" htmlFor="business-target-customers">
          Target customers
        </label>
        <input
          id="business-target-customers"
          type="text"
          value={draft.targetCustomers}
          onChange={(event) => {
            const targetCustomers = event.target.value;
            onChange((prev) => ({ ...prev, targetCustomers }));
          }}
        />

        <label className="field-label" htmlFor="business-raw-description">
          Original briefing
        </label>
        <textarea
          id="business-raw-description"
          rows={3}
          value={draft.rawDescription}
          onChange={(event) => {
            const rawDescription = event.target.value;
            onChange((prev) => ({ ...prev, rawDescription }));
          }}
        />
      </fieldset>

      <fieldset className="form-section">
        <legend>Location</legend>
        <label className="field-label" htmlFor="location-city">
          City
        </label>
        <input
          id="location-city"
          type="text"
          value={draft.location.city}
          onChange={(event) => {
            const city = event.target.value;
            onChange((prev) => ({ ...prev, location: { ...prev.location, city } }));
          }}
        />
        <label className="field-label" htmlFor="location-region">
          Region
        </label>
        <input
          id="location-region"
          type="text"
          value={draft.location.region}
          onChange={(event) => {
            const region = event.target.value;
            onChange((prev) => ({ ...prev, location: { ...prev.location, region } }));
          }}
        />
        <label className="field-label" htmlFor="location-country">
          Country (2-letter code)
        </label>
        <input
          id="location-country"
          type="text"
          maxLength={2}
          value={draft.location.country}
          onChange={(event) => {
            const country = event.target.value;
            onChange((prev) => ({ ...prev, location: { ...prev.location, country } }));
          }}
        />
        <label className="field-label" htmlFor="location-postal-code">
          Postal code
        </label>
        <input
          id="location-postal-code"
          type="text"
          value={draft.location.postalCode}
          onChange={(event) => {
            const postalCode = event.target.value;
            onChange((prev) => ({ ...prev, location: { ...prev.location, postalCode } }));
          }}
        />
      </fieldset>

      <fieldset className="form-section">
        <legend>Services</legend>
        {draft.services.map((service, index) => (
          <div className="service-row" key={service.key}>
            <input
              type="text"
              aria-label={`Service #${index + 1} name`}
              placeholder="Service name"
              value={service.name}
              onChange={(event) => {
                const name = event.target.value;
                onChange((prev) => ({
                  ...prev,
                  services: prev.services.map((s, i) => (i === index ? { ...s, name } : s)),
                }));
              }}
            />
            <input
              type="text"
              aria-label={`Service #${index + 1} description`}
              placeholder="Description"
              value={service.description}
              onChange={(event) => {
                const description = event.target.value;
                onChange((prev) => ({
                  ...prev,
                  services: prev.services.map((s, i) => (i === index ? { ...s, description } : s)),
                }));
              }}
            />
            <input
              type="text"
              aria-label={`Service #${index + 1} category`}
              placeholder="Category (optional)"
              value={service.category}
              onChange={(event) => {
                const category = event.target.value;
                onChange((prev) => ({
                  ...prev,
                  services: prev.services.map((s, i) => (i === index ? { ...s, category } : s)),
                }));
              }}
            />
            <button
              type="button"
              onClick={() => onChange((prev) => ({ ...prev, services: prev.services.filter((_, i) => i !== index) }))}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() =>
            onChange((prev) => ({
              ...prev,
              services: [...prev.services, { key: nextServiceDraftKey(), name: "", description: "", category: "" }],
            }))
          }
        >
          Add service
        </button>
      </fieldset>

      <fieldset className="form-section">
        <legend>Contact</legend>
        <label className="field-label" htmlFor="contact-email">
          Email
        </label>
        <input
          id="contact-email"
          type="text"
          value={draft.contact.email}
          onChange={(event) => {
            const email = event.target.value;
            onChange((prev) => ({ ...prev, contact: { ...prev.contact, email } }));
          }}
        />
        <label className="field-label" htmlFor="contact-phone">
          Phone
        </label>
        <input
          id="contact-phone"
          type="text"
          value={draft.contact.phone}
          onChange={(event) => {
            const phone = event.target.value;
            onChange((prev) => ({ ...prev, contact: { ...prev.contact, phone } }));
          }}
        />
        <label className="field-label" htmlFor="contact-whatsapp">
          WhatsApp
        </label>
        <input
          id="contact-whatsapp"
          type="text"
          value={draft.contact.whatsapp}
          onChange={(event) => {
            const whatsapp = event.target.value;
            onChange((prev) => ({ ...prev, contact: { ...prev.contact, whatsapp } }));
          }}
        />
        <label className="field-label" htmlFor="contact-website">
          Website
        </label>
        <input
          id="contact-website"
          type="text"
          value={draft.contact.website}
          onChange={(event) => {
            const website = event.target.value;
            onChange((prev) => ({ ...prev, contact: { ...prev.contact, website } }));
          }}
        />
      </fieldset>

      <fieldset className="form-section">
        <legend>Lead sources</legend>
        {LEAD_SOURCE_OPTIONS.map((option) => (
          <label className="checkbox-field" key={option.value}>
            <input
              type="checkbox"
              checked={draft.leadSources.includes(option.value)}
              onChange={(event) => {
                const checked = event.target.checked;
                onChange((prev) => ({
                  ...prev,
                  leadSources: checked
                    ? [...prev.leadSources, option.value]
                    : prev.leadSources.filter((source) => source !== option.value),
                }));
              }}
            />
            {option.label}
          </label>
        ))}
      </fieldset>

      <fieldset className="form-section">
        <legend>Proposed automations</legend>
        {hasProposal && (
          <AutomationRecommendationAction
            vertical={draft.vertical}
            tenantId={tenantId}
            autoShow={!isEditingExisting}
            onApply={(recommendation) =>
              onChange((prev) => ({
                ...prev,
                automation: {
                  ...prev.automation,
                  leadNotifications: recommendation.lead_notifications,
                  customerAcknowledgement: recommendation.customer_acknowledgement,
                  followUpEnabled: recommendation.follow_up_enabled,
                  followUpDelayHours: recommendation.follow_up_delay_hours,
                },
              }))
            }
          />
        )}
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={draft.automation.leadCapture}
            onChange={(event) => {
              const leadCapture = event.target.checked;
              onChange((prev) => ({ ...prev, automation: { ...prev.automation, leadCapture } }));
            }}
          />
          Capture leads automatically
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={draft.automation.leadNotifications}
            onChange={(event) => {
              const leadNotifications = event.target.checked;
              onChange((prev) => ({ ...prev, automation: { ...prev.automation, leadNotifications } }));
            }}
          />
          Notify the team of new leads
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={draft.automation.customerAcknowledgement}
            onChange={(event) => {
              const customerAcknowledgement = event.target.checked;
              onChange((prev) => ({ ...prev, automation: { ...prev.automation, customerAcknowledgement } }));
            }}
          />
          Send the customer an acknowledgement
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={draft.automation.followUpEnabled}
            onChange={(event) => {
              const followUpEnabled = event.target.checked;
              onChange((prev) => ({ ...prev, automation: { ...prev.automation, followUpEnabled } }));
            }}
          />
          Follow up automatically
        </label>
        <label className="field-label" htmlFor="automation-follow-up-delay">
          Follow-up delay (hours)
        </label>
        <input
          id="automation-follow-up-delay"
          type="number"
          min={1}
          max={720}
          step={1}
          // A cleared field is NaN in the draft (validateDraft flags it
          // if the user tries to save that way) — rendered as an empty
          // input here, never the literal text "NaN".
          value={Number.isNaN(draft.automation.followUpDelayHours) ? "" : draft.automation.followUpDelayHours}
          disabled={!draft.automation.followUpEnabled}
          onChange={(event) => {
            const followUpDelayHours = event.target.valueAsNumber;
            onChange((prev) => ({ ...prev, automation: { ...prev.automation, followUpDelayHours } }));
          }}
        />
      </fieldset>

      <details className="json-preview">
        <summary>Technical preview (raw proposal JSON)</summary>
        <pre>{JSON.stringify(analysis.proposed_config, null, 2)}</pre>
      </details>

      {createError && <ErrorBanner error={createError} />}

      <div className="proposal-actions">
        <button type="button" onClick={onBack} disabled={isCreating}>
          Back
        </button>
        <button type="button" onClick={onCreate} disabled={isCreating}>
          {isCreating ? "Saving…" : submitLabel}
        </button>
      </div>
    </div>
  );
}
