import { useMemo, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { CreativeGeneration, CreativeGenerationType, CreativeProviderAvailability } from "../../lib/api";

interface GenerationsPanelProps {
  generations: CreativeGeneration[] | null;
  isLoading: boolean;
  error: string | null;
  providers: CreativeProviderAvailability[] | null;
  /** POST .../creative-generations (app.routers.creative) — runs the
   * CreativeOrchestrator synchronously and resolves with the finished
   * (COMPLETED or FAILED) record. Generate, regenerate, and "generate a
   * variation" are all this same call (Section 16) — the currently
   * published website is never touched by it. */
  onGenerate: (generationType: CreativeGenerationType) => Promise<CreativeGeneration>;
}

const TYPE_OPTIONS: CreativeGenerationType[] = ["website", "website_concept", "image", "video", "visual_asset"];

const STATUS_LABELS: Record<CreativeGeneration["status"], string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

function formatDuration(startedAt: string | null, completedAt: string | null): string | null {
  if (!startedAt || !completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** Generation history + trigger (Section 13/16): every CreativeProvider
 * call this business has made, most recent first, plus the one action
 * that starts a new one. A generation here never applies its own result
 * to the live site — publishing a website remains its own separate,
 * explicit action (see WebsitePublish) — so triggering a generation,
 * even at PREMIUM/CINEMATIC level, never risks the currently published
 * site.
 *
 * `providers` (Phase 13) disables a generation type no *available*
 * provider actually supports — Internal only supports website/
 * website_concept today, so image/video/visual_asset are disabled with
 * an explicit reason rather than left selectable to fail every time. */
export function GenerationsPanel({ generations, isLoading, error, providers, onGenerate }: GenerationsPanelProps) {
  const [generationType, setGenerationType] = useState<CreativeGenerationType>("website");
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const supportedTypes = useMemo(() => {
    const supported = new Set<CreativeGenerationType>();
    for (const provider of providers ?? []) {
      if (provider.available) {
        for (const capability of provider.capabilities) supported.add(capability);
      }
    }
    return supported;
  }, [providers]);

  async function handleGenerate() {
    setIsGenerating(true);
    setGenerateError(null);
    try {
      await onGenerate(generationType);
    } catch (caught) {
      setGenerateError(friendlyErrorMessage(caught, "Generation failed."));
    } finally {
      setIsGenerating(false);
    }
  }

  const totalCost = (generations ?? []).reduce((sum, g) => sum + (g.estimated_cost ?? 0), 0);

  return (
    <div className="generations-panel">
      {error && <p className="banner banner--error">Could not load generation history: {error}</p>}
      {isLoading ? (
        <p className="field-hint">Loading generation history…</p>
      ) : !generations || generations.length === 0 ? (
        <p className="field-hint">No generations yet.</p>
      ) : (
        <>
          <p className="field-hint">
            {generations.length} generation{generations.length === 1 ? "" : "s"}
            {totalCost > 0 && ` · estimated cost so far: €${totalCost.toFixed(2)}`}
          </p>
          <ul className="generations-panel__list">
            {generations.map((generation) => {
              const duration = formatDuration(generation.started_at, generation.completed_at);
              return (
                <li key={generation.id} className="generations-panel__item">
                  <div>
                    <strong>{generation.provider}</strong> · {generation.generation_type} · {generation.creative_level}
                  </div>
                  <div>
                    {STATUS_LABELS[generation.status]}
                    {duration && ` · ${duration}`}
                    {generation.credits_used != null && ` · ${generation.credits_used} credits`}
                    {generation.estimated_cost != null && ` · €${generation.estimated_cost.toFixed(2)}`}
                  </div>
                  {generation.error && <p className="banner banner--error">{generation.error}</p>}
                  <div className="field-hint">{new Date(generation.created_at).toLocaleString()}</div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {generateError && <p className="banner banner--error">{generateError}</p>}
      <div className="generations-panel__form">
        <select
          value={generationType}
          onChange={(event) => setGenerationType(event.target.value as CreativeGenerationType)}
        >
          {TYPE_OPTIONS.map((type) => (
            <option key={type} value={type} disabled={providers != null && !supportedTypes.has(type)}>
              {type}
              {providers != null && !supportedTypes.has(type) ? " (no available provider)" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isGenerating || (providers != null && !supportedTypes.has(generationType))}
        >
          {isGenerating ? "Generating…" : "Generate"}
        </button>
      </div>
    </div>
  );
}
