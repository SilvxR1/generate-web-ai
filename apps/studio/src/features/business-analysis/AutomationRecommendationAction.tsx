import { useEffect, useState } from "react";
import type { BusinessVertical } from "@generate-web-ai/business-config-types";
import { getAutomationRecommendation, type AutomationRecommendation } from "../../lib/api";
import { BUSINESS_VERTICAL_OPTIONS } from "./draft";
import { friendlyErrorMessage } from "./errors";

interface AutomationRecommendationActionProps {
  vertical: BusinessVertical;
  tenantId: string;
  /** true for a just-analyzed proposal: fetch automatically and show
   * the recommendation as soon as it loads, no click required just to
   * *see* it. false when editing an already-persisted business: stays
   * inert until the user clicks "Show recommended automation" —
   * nothing about this vertical's recommendation is surfaced for an
   * existing business unless asked for. Either way, *applying* it
   * always needs its own separate, explicit click — this prop only
   * ever controls whether the summary appears on its own. */
  autoShow: boolean;
  /** Called only when the user clicks "Apply recommended automation" —
   * never on load, auto or manual. The caller writes the four values
   * onto its own normal automation draft; nothing here saves anything
   * itself or persists a second copy of the template. */
  onApply: (recommendation: AutomationRecommendation) => void;
}

type UiState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "loaded"; recommendation: AutomationRecommendation }
  | { kind: "failed"; error: string };

function describeVertical(vertical: BusinessVertical): string {
  const label = BUSINESS_VERTICAL_OPTIONS.find((option) => option.value === vertical)?.label ?? vertical;
  return label.toLowerCase();
}

function summarizeRecommendation(recommendation: AutomationRecommendation): string {
  const parts: string[] = [];
  if (recommendation.lead_notifications) parts.push("Internal notification");
  if (recommendation.customer_acknowledgement) parts.push("Customer acknowledgement");
  if (recommendation.follow_up_enabled) parts.push(`Follow-up after ${recommendation.follow_up_delay_hours}h`);
  return parts.length > 0 ? parts.join(" · ") : "No automation actions";
}

/** Recommended-for-this-vertical summary (app.domain.workflow_config.
 * vertical_templates, via GET /businesses/automation-recommendation —
 * a pure lookup, never a second persisted config) plus the one action
 * that writes it onto the draft: "Apply recommended automation".
 * *Showing* the summary can happen automatically (`autoShow`); writing
 * it into the draft never does — that's always this component's own
 * explicit button click, and the caller's own onChange, never this
 * component reaching into anything itself. */
export function AutomationRecommendationAction({
  vertical,
  tenantId,
  autoShow,
  onApply,
}: AutomationRecommendationActionProps) {
  const [ui, setUi] = useState<UiState>({ kind: "idle" });

  useEffect(() => {
    if (!autoShow) {
      setUi({ kind: "idle" });
      return;
    }
    let cancelled = false;
    setUi({ kind: "loading" });
    getAutomationRecommendation(vertical, tenantId)
      .then((recommendation) => {
        if (!cancelled) setUi({ kind: "loaded", recommendation });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setUi({ kind: "failed", error: friendlyErrorMessage(error, "Could not load a recommendation.") });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [autoShow, vertical, tenantId]);

  async function handleManualFetch() {
    setUi({ kind: "loading" });
    try {
      const recommendation = await getAutomationRecommendation(vertical, tenantId);
      setUi({ kind: "loaded", recommendation });
    } catch (caught) {
      setUi({ kind: "failed", error: friendlyErrorMessage(caught, "Could not load a recommendation.") });
    }
  }

  if (ui.kind === "idle") {
    if (autoShow) return null; // the effect above is about to move past idle
    return (
      <div className="automation-recommendation">
        <button type="button" onClick={handleManualFetch}>
          Show recommended automation
        </button>
      </div>
    );
  }

  if (ui.kind === "loading") {
    return <p className="field-hint automation-recommendation">Loading recommended automation…</p>;
  }

  if (ui.kind === "failed") {
    // autoShow: fail silently — a passive suggestion that couldn't
    // load should never alarm a user who didn't ask for it. Manual:
    // the user did ask, so offer a retry.
    if (autoShow) return null;
    return (
      <div className="automation-recommendation">
        <p className="field-hint">Could not load a recommendation: {ui.error}</p>
        <button type="button" onClick={handleManualFetch}>
          Try again
        </button>
      </div>
    );
  }

  const { recommendation } = ui;
  return (
    <div className="automation-recommendation">
      <p className="field-hint">
        <span>{`Recommended for ${describeVertical(vertical)}`}</span>
        <br />
        <span>{summarizeRecommendation(recommendation)}</span>
      </p>
      <button type="button" onClick={() => onApply(recommendation)}>
        Apply recommended automation
      </button>
    </div>
  );
}
