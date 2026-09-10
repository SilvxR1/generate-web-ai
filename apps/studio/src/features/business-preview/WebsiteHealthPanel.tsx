import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { HealthStatus, WebsiteHealth } from "../../lib/api";

interface WebsiteHealthPanelProps {
  health: WebsiteHealth | null;
  isLoading: boolean;
  onCheckNow: () => Promise<WebsiteHealth>;
}

const STATUS_LABELS: Record<HealthStatus, string> = {
  healthy: "✓ Healthy",
  degraded: "⚠ Degraded",
  down: "✕ Down",
  unknown: "? Unknown",
};

/** A sub-check's status badge — UNKNOWN deliberately never renders with
 * the same visual weight as HEALTHY (P1.5: "Do not present UNKNOWN as
 * HEALTHY"). */
function StatusBadge({ status }: { status: HealthStatus }) {
  return <span className={`health-badge health-badge--${status}`}>{STATUS_LABELS[status]}</span>;
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Website Health (P1.4/P1.5): the latest HTTP/DNS/TLS/deployment/form
 * snapshot for this business's live website, plus a "Check now" action
 * that runs a real check on demand. Never invents a value — a business
 * with no published website (or no check run yet) shows that state
 * plainly instead of a fabricated "Healthy". */
export function WebsiteHealthPanel({ health, isLoading, onCheckNow }: WebsiteHealthPanelProps) {
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCheckNow() {
    setIsChecking(true);
    setError(null);
    try {
      await onCheckNow();
    } catch (caught) {
      setError(friendlyErrorMessage(caught, "Could not run a health check right now."));
    } finally {
      setIsChecking(false);
    }
  }

  if (isLoading) {
    return <p>Loading website health…</p>;
  }

  return (
    <div className="website-health-panel">
      {error && <p className="banner banner--error">{error}</p>}

      {!health && <p className="field-hint">No health check has been run yet for this business.</p>}

      {health && (
        <dl className="website-health-panel__grid">
          <dt>Overall</dt>
          <dd>
            <StatusBadge status={health.overall_status} />
          </dd>

          <dt>HTTP</dt>
          <dd>
            <StatusBadge status={health.http_status} />
            {health.http_status_code != null && ` ${health.http_status_code}`}
          </dd>

          <dt>Latency</dt>
          <dd>{health.http_latency_ms != null ? `${Math.round(health.http_latency_ms)} ms` : "—"}</dd>

          <dt>DNS</dt>
          <dd>
            <StatusBadge status={health.dns_status} />
          </dd>

          <dt>SSL</dt>
          <dd>
            <StatusBadge status={health.tls_status} />
            {health.tls_days_remaining != null && ` ${health.tls_days_remaining} days remaining`}
          </dd>

          <dt>Deployment</dt>
          <dd>
            <StatusBadge status={health.deployment_status} />
          </dd>

          <dt>Contact form</dt>
          <dd>
            <StatusBadge status={health.form_status} />
          </dd>

          <dt>Last checked</dt>
          <dd>{timeAgo(health.checked_at)}</dd>

          {health.error_summary && (
            <>
              <dt>Issue</dt>
              <dd>{health.error_summary}</dd>
            </>
          )}
        </dl>
      )}

      <button type="button" onClick={handleCheckNow} disabled={isChecking}>
        {isChecking ? "Checking…" : "Check now"}
      </button>
    </div>
  );
}
