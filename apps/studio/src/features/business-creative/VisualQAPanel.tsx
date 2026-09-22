import type { CreativeDirection } from "../../lib/api";
import { visualQaView } from "./visualQa";

// P2.7: read-only display of one direction's Image QA result. No configuration
// UI — an operator can only see what ran, what it found, and what did not run.
export function VisualQAPanel({ direction }: { direction: CreativeDirection }) {
  const qa = visualQaView(direction);
  if (qa === null) return null; // no generated image (an internal-fallback direction) — nothing to show

  return (
    <div className="generative-workflow-panel__visual-qa">
      <p className="field-hint">
        <strong>Visual QA: {qa.overallLabel}</strong>
        {qa.totalCount > 0 && ` (${qa.performedCount}/${qa.totalCount} checks performed)`}
        {!qa.approvalEligible && " — blocks recommendation and website generation"}
      </p>
      {qa.checks.length > 0 && (
        <ul className="generative-workflow-panel__visual-qa-checks">
          {qa.checks.map((check) => (
            <li key={check.name} className="field-hint">
              {check.headline}
              {check.requestedSwatches.length > 0 && (
                <span className="generative-workflow-panel__visual-qa-swatches">
                  {" requested "}
                  {check.requestedSwatches.map((color) => (
                    <span key={`r-${color}`} className="site-preview__swatch" style={{ background: color }} title={color} />
                  ))}
                  {check.detectedSwatches.length > 0 && (
                    <>
                      {" · detected "}
                      {check.detectedSwatches.map((color) => (
                        <span key={`d-${color}`} className="site-preview__swatch" style={{ background: color }} title={color} />
                      ))}
                    </>
                  )}
                </span>
              )}
              {check.details.map((line) => (
                <span key={line} className="generative-workflow-panel__visual-qa-detail">
                  {" — "}
                  {line}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {qa.notPerformedLabels.length > 0 && (
        <p className="field-hint generative-workflow-panel__visual-qa-gap">
          Not covered: {qa.notPerformedLabels.join(", ")}
        </p>
      )}
    </div>
  );
}
