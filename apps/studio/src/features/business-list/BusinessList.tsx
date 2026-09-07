import { Link } from "react-router-dom";
import { BUSINESS_VERTICAL_OPTIONS } from "../business-analysis/draft";
import type { BusinessSummary } from "../../lib/api";

interface BusinessListProps {
  businesses: BusinessSummary[];
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
export function BusinessList({ businesses }: BusinessListProps) {
  return (
    <ul className="business-list">
      {businesses.map((business) => {
        const location = locationLabel(business);
        return (
          <li key={business.id} className="business-card">
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
            <Link className="business-card__open" to={`/businesses/${business.id}`}>
              Open
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
