import { useState } from "react";
import type { BusinessMetrics, MetricsWindow } from "../../lib/api";

interface BusinessMetricsPanelProps {
  metrics: BusinessMetrics | null;
  isLoading: boolean;
  window: MetricsWindow;
  onWindowChange: (window: MetricsWindow) => void;
}

const WINDOW_OPTIONS: { value: MetricsWindow; label: string }[] = [
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "90d", label: "90 days" },
];

/** Renders a count, or "No data yet" when the backend reports the
 * metric as genuinely unavailable (never a fabricated 0 — P1.8: "If
 * data is unavailable... show 'No data yet' not zero unless zero is
 * actually known"). */
function MetricValue({ value }: { value: number | null }) {
  if (value === null) return <span className="field-hint">No data yet</span>;
  return <strong>{value.toLocaleString()}</strong>;
}

/** Business Metrics (P1.8): website visits, WhatsApp/phone/email clicks,
 * form leads, and conversion rate over a selectable window. Every
 * number comes straight from the backend's real aggregation — this
 * component never computes or estimates anything itself. */
export function BusinessMetricsPanel({ metrics, isLoading, window, onWindowChange }: BusinessMetricsPanelProps) {
  const [pendingWindow, setPendingWindow] = useState<MetricsWindow>(window);

  function handleWindowChange(next: MetricsWindow) {
    setPendingWindow(next);
    onWindowChange(next);
  }

  return (
    <div className="business-metrics-panel">
      <div className="business-metrics-panel__window">
        <label>
          Last{" "}
          <select value={pendingWindow} onChange={(event) => handleWindowChange(event.target.value as MetricsWindow)}>
            {WINDOW_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {isLoading && <p>Loading metrics…</p>}

      {!isLoading && metrics && (
        <dl className="business-metrics-panel__grid">
          <dt>Website visits</dt>
          <dd>
            <MetricValue value={metrics.website_visits} />
          </dd>

          <dt>WhatsApp clicks</dt>
          <dd>
            <MetricValue value={metrics.whatsapp_clicks} />
          </dd>

          <dt>Form leads</dt>
          <dd>
            <strong>{metrics.form_leads.toLocaleString()}</strong>
          </dd>

          <dt>Phone clicks</dt>
          <dd>
            <MetricValue value={metrics.phone_clicks} />
          </dd>

          <dt>Email clicks</dt>
          <dd>
            <MetricValue value={metrics.email_clicks} />
          </dd>

          <dt>Lead conversion</dt>
          <dd>
            {metrics.lead_conversion_rate === null ? (
              <span className="field-hint">No data yet</span>
            ) : (
              <strong>{(metrics.lead_conversion_rate * 100).toFixed(1)}%</strong>
            )}
          </dd>
        </dl>
      )}
    </div>
  );
}
