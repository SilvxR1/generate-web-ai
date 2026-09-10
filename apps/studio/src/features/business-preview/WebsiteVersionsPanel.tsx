import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { WebsiteState, WebsiteVersionSummary } from "../../lib/api";

interface WebsiteVersionsPanelProps {
  versions: WebsiteVersionSummary[] | null;
  isLoading: boolean;
  onRollback: (versionId: string) => Promise<WebsiteState>;
}

type UiState = { kind: "idle" } | { kind: "rollingBack"; versionId: string } | { kind: "error"; message: string };

/** History of every successful publish, most recent first, with a
 * "Roll back to this version" action on every entry except the current
 * one. Rollback is a real republish server-side (see the backend's
 * app.publishing.versions.rollback_to_version) — this component only
 * tracks its own in-flight/error UI state around that call, never a
 * local "which version is live" guess (that's always `versions`,
 * reread from the backend after a successful rollback). */
export function WebsiteVersionsPanel({ versions, isLoading, onRollback }: WebsiteVersionsPanelProps) {
  const [ui, setUi] = useState<UiState>({ kind: "idle" });

  if (isLoading) {
    return <p>Loading version history…</p>;
  }

  if (!versions || versions.length === 0) {
    return <p className="field-hint">No published versions yet — publish this website to start its history.</p>;
  }

  async function handleRollback(versionId: string) {
    setUi({ kind: "rollingBack", versionId });
    try {
      await onRollback(versionId);
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "error", message: friendlyErrorMessage(caught, "Could not roll back to this version.") });
    }
  }

  return (
    <div className="website-versions-panel">
      {ui.kind === "error" && <p className="banner banner--error">{ui.message}</p>}
      <ul className="website-versions-panel__list">
        {versions.map((version) => (
          <li className="website-versions-panel__item" key={version.id}>
            <span>{new Date(version.published_at).toLocaleString()}</span>
            {version.is_current ? (
              <span className="badge">Currently live</span>
            ) : (
              <button
                type="button"
                onClick={() => handleRollback(version.id)}
                disabled={ui.kind === "rollingBack"}
              >
                {ui.kind === "rollingBack" && ui.versionId === version.id ? "Rolling back…" : "Roll back to this version"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
