import type { WorkflowConfig } from "@generate-web-ai/workflow-config-types";
import { useState } from "react";
import { ErrorBanner } from "../business-analysis/ErrorBanner";
import { categorizeActivationError, type CategorizedError } from "../business-analysis/errors";
import type { AutomationState } from "../../lib/api";
import { describeCapability, describeFollowUp, describeNode, describeTrigger, layerWorkflow } from "./workflow";

interface WorkflowPreviewProps {
  workflow: WorkflowConfig | null;
  isLoading: boolean;
  error: CategorizedError | null;
  /** The business's *persisted* automation state (backend's
   * app.db.models.workflow.Workflow, loaded fresh whenever the preview
   * step opens) — the source of truth for Active/Inactive. Never
   * inferred from this component's own past actions. */
  automationState: AutomationState | null;
  isLoadingAutomationState: boolean;
  onActivate: () => Promise<AutomationState>;
  onDeactivate: () => Promise<AutomationState>;
}

// Local, ephemeral UI feedback only — never the source of truth for
// whether automation is active (that's always `automationState`, reread
// from the backend). "confirming" is the pre-activation confirmation
// step; "busy" covers the in-flight request; "failed" is the last
// attempt's outcome, cleared as soon as another attempt starts.
type UiState =
  | { kind: "idle" }
  | { kind: "confirming" }
  | { kind: "activating" }
  | { kind: "deactivating" }
  | { kind: "failed"; action: "activate" | "deactivate"; error: CategorizedError };

export function WorkflowPreview({
  workflow,
  isLoading,
  error,
  automationState,
  isLoadingAutomationState,
  onActivate,
  onDeactivate,
}: WorkflowPreviewProps) {
  const [ui, setUi] = useState<UiState>({ kind: "idle" });

  if (isLoading || isLoadingAutomationState) {
    return <p>Loading automation preview…</p>;
  }
  if (error) {
    return <ErrorBanner error={error} />;
  }
  if (!workflow) {
    return (
      <p className="banner banner--warning">
        No automation is configured for this business yet. Enable "Capture leads automatically" in the proposal to
        preview one.
      </p>
    );
  }

  const layers = layerWorkflow(workflow);
  const actionLabels = (workflow.nodes ?? []).filter((node) => "action" in node).map((node) => describeNode(node));
  const isActive = automationState?.status === "active";

  async function handleConfirmActivate() {
    setUi({ kind: "activating" });
    try {
      await onActivate();
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "failed", action: "activate", error: categorizeActivationError(caught) });
    }
  }

  async function handleDeactivate() {
    setUi({ kind: "deactivating" });
    try {
      await onDeactivate();
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "failed", action: "deactivate", error: categorizeActivationError(caught) });
    }
  }

  return (
    <div className="workflow-preview">
      <div className="workflow-diagram">
        {layers.map((layer, levelIndex) => (
          <div className="workflow-diagram__level" key={layer.map((box) => box.id).join("-")}>
            <div className="workflow-diagram__row">
              {layer.map((box) => (
                <div className="workflow-diagram__node" key={box.id}>
                  {box.label}
                </div>
              ))}
            </div>
            {levelIndex < layers.length - 1 && (
              <div className="workflow-diagram__connector">{(layers[levelIndex + 1]?.length ?? 0) > 1 ? "↙   ↘" : "↓"}</div>
            )}
          </div>
        ))}
      </div>

      <dl className="workflow-preview__facts">
        <dt>Workflow name</dt>
        <dd>{workflow.name}</dd>
        <dt>Trigger</dt>
        <dd>{describeTrigger(workflow.trigger)}</dd>
        <dt>Actions</dt>
        <dd>{actionLabels.join(", ")}</dd>
        <dt>Follow-up</dt>
        <dd>{describeFollowUp(workflow)}</dd>
        <dt>Required capabilities</dt>
        <dd>
          <ul className="workflow-preview__capabilities">
            {workflow.required_capabilities.map((capability) => (
              <li key={capability}>{describeCapability(capability)}</li>
            ))}
          </ul>
        </dd>
      </dl>

      <div className="activation-panel">
        {ui.kind === "activating" && <p>Activating…</p>}
        {ui.kind === "deactivating" && <p>Deactivating…</p>}

        {ui.kind === "failed" && (
          <>
            <ErrorBanner error={ui.error} />
            <button type="button" onClick={ui.action === "activate" ? handleConfirmActivate : handleDeactivate}>
              Try again
            </button>
          </>
        )}

        {ui.kind === "idle" && isActive && (
          <>
            <p className="banner banner--ok">
              Active — automation workflow <code>{automationState?.remote_id}</code> is running.
            </p>
            <button type="button" onClick={handleDeactivate}>
              Deactivate
            </button>
          </>
        )}

        {ui.kind === "idle" && !isActive && (
          <button type="button" onClick={() => setUi({ kind: "confirming" })}>
            Activate automation
          </button>
        )}

        {ui.kind === "confirming" && (
          <div className="activation-confirm">
            <p className="banner__title">Confirm activation</p>
            <dl className="workflow-preview__facts">
              <dt>Trigger</dt>
              <dd>{describeTrigger(workflow.trigger)}</dd>
              <dt>Actions</dt>
              <dd>{actionLabels.join(", ")}</dd>
              <dt>Follow-up</dt>
              <dd>{describeFollowUp(workflow)}</dd>
              <dt>Required capabilities</dt>
              <dd>{workflow.required_capabilities.map(describeCapability).join(", ")}</dd>
            </dl>
            <p className="activation-confirm__warning">
              This will start executing real actions (storing leads, sending emails and notifications) every time a
              lead comes in. Make sure this business's contact/lead settings are correct before continuing.
            </p>
            <div className="proposal-actions">
              <button type="button" onClick={() => setUi({ kind: "idle" })}>
                Cancel
              </button>
              <button type="button" onClick={handleConfirmActivate}>
                Confirm activate
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
