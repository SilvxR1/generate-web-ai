import type { ProductionReadinessReport } from "../../lib/api";

interface ProductionReadinessPanelProps {
  report: ProductionReadinessReport | null;
  isLoading: boolean;
}

/** Read-only checklist synthesizing signals Studio already fetches
 * elsewhere on this page (website state, custom domain, legal profile
 * completeness). Deliberately never disables or gates the Publish
 * button below — only `blocking` checks (hosting/config, both surfaced
 * with their own clear errors already if they fail) are genuine
 * technical blockers; everything else here is informational, per P0's
 * "only real technical blockers should prevent publishing" constraint.
 */
export function ProductionReadinessPanel({ report, isLoading }: ProductionReadinessPanelProps) {
  if (isLoading) {
    return <p>Loading readiness checklist…</p>;
  }

  if (!report) {
    return null;
  }

  return (
    <div className="production-readiness-panel">
      {report.has_blocking_issues && (
        <p className="banner banner--warning">
          One or more technical requirements aren't met yet — publishing will fail until they are.
        </p>
      )}
      <ul className="production-readiness-panel__list">
        {report.checks.map((check) => (
          <li className="production-readiness-panel__item" key={check.id}>
            <span className={`badge ${check.ready ? "badge--ready" : check.blocking ? "badge--blocked" : "badge--info"}`}>
              {check.ready ? "Ready" : check.blocking ? "Blocked" : "Incomplete"}
            </span>
            <span>
              <strong>{check.label}:</strong> {check.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
