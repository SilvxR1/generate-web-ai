import type { CreativeConfig } from "@generate-web-ai/business-config-types";
import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";

interface CreativeConfigPanelProps {
  config: CreativeConfig | null;
  isLoading: boolean;
  /** PUT .../creative-config (app.routers.creative) — resolves with the
   * saved CreativeConfig. The caller (CreativeSection) is the one that
   * actually updates state; this component only tracks its own
   * in-flight/error UI around the call. */
  onSave: (config: CreativeConfig) => Promise<CreativeConfig>;
}

type Strategy = "preserve" | "evolve" | "new_direction";
type Level = "basic" | "professional" | "premium" | "cinematic";

const STRATEGY_OPTIONS: Strategy[] = ["preserve", "evolve", "new_direction"];
const STRATEGY_LABELS: Record<Strategy, string> = {
  preserve: "Preserve — keep logo, colors, photography; improve layout & UX",
  evolve: "Evolve — keep brand recognition; modernize color/typography/layout",
  new_direction: "New direction — use business facts as context, new creative direction",
};

const LEVEL_OPTIONS: Level[] = ["basic", "professional", "premium", "cinematic"];
const LEVEL_LABELS: Record<Level, string> = {
  basic: "Basic — internal generation",
  professional: "Professional — premium design generation",
  premium: "Premium — advanced design + imagery",
  cinematic: "Cinematic — high-end visuals, video where supported",
};

/** Creative strategy + level controls (Section 5/12 of the Creative
 * Orchestrator design) — a business's own CreativeConfig, read/written
 * through GET/PUT .../creative-config. Requires the business to already
 * have a BusinessConfig (the backend 409s otherwise; onSave surfaces
 * that same way every other save error in this app does). */
export function CreativeConfigPanel({ config, isLoading, onSave }: CreativeConfigPanelProps) {
  const [draft, setDraft] = useState<CreativeConfig | null>(config);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedConfig, setSavedConfig] = useState<CreativeConfig | null>(config);

  // Keep the draft in sync whenever a fresh config arrives from the
  // parent (first load, or a reload token bump) — but never clobber a
  // user's in-progress edit with a stale re-fetch of the same data.
  if (config !== savedConfig && draft === savedConfig) {
    setSavedConfig(config);
    setDraft(config);
  }

  if (isLoading) {
    return <p className="field-hint">Loading creative strategy…</p>;
  }
  if (!draft) {
    return <p className="field-hint">Save this business's basic details first to set a creative strategy.</p>;
  }

  const isDirty = draft.strategy !== savedConfig?.strategy || draft.level !== savedConfig?.level;

  async function handleSave() {
    if (!draft) return;
    setIsSaving(true);
    setError(null);
    try {
      const saved = await onSave(draft);
      setSavedConfig(saved);
      setDraft(saved);
    } catch (caught) {
      setError(friendlyErrorMessage(caught, "Could not save creative strategy."));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="creative-config-panel">
      {error && <p className="banner banner--error">{error}</p>}
      <label>
        Creative strategy
        <select
          value={draft.strategy}
          onChange={(event) => setDraft({ ...draft, strategy: event.target.value as CreativeConfig["strategy"] })}
        >
          {STRATEGY_OPTIONS.map((strategy) => (
            <option key={strategy} value={strategy}>
              {STRATEGY_LABELS[strategy]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Creative level
        <select
          value={draft.level}
          onChange={(event) => setDraft({ ...draft, level: event.target.value as CreativeConfig["level"] })}
        >
          {LEVEL_OPTIONS.map((level) => (
            <option key={level} value={level}>
              {LEVEL_LABELS[level]}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={handleSave} disabled={!isDirty || isSaving}>
        {isSaving ? "Saving…" : "Save creative strategy"}
      </button>
    </div>
  );
}
