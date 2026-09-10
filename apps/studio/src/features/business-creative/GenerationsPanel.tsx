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

// "website" is the one primary, always-meaningful action (see the big
// button below) — every other type is either an internal-only concept
// with no operator-facing output today (`website_concept`: Internal's
// generate_concept returns static metadata, nothing worth showing a
// user) or unsupported by any configured provider yet (image/video/
// visual_asset). Kept available in "Advanced" for a future premium
// provider, never presented as if it already works (LR-03: "do not
// clutter the main workflow with unsupported types").
const ADVANCED_TYPE_OPTIONS: CreativeGenerationType[] = ["website", "website_concept", "image", "video", "visual_asset"];

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
  const [advancedType, setAdvancedType] = useState<CreativeGenerationType>("website");
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

  async function handleGenerate(generationType: CreativeGenerationType) {
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

      <div className="generations-panel__primary">
        <button
          type="button"
          onClick={() => handleGenerate("website")}
          disabled={isGenerating || (providers != null && !supportedTypes.has("website"))}
        >
          {isGenerating ? "Generating website…" : "Generate website"}
        </button>
        <p className="field-hint">
          Builds a website from this business's current information, brand, and photos. You'll review it below before
          it ever goes live.
        </p>
      </div>

      <details className="generations-panel__advanced">
        <summary>Advanced generation options</summary>
        <p className="field-hint">
          Other generation types this platform's providers can produce. Most businesses never need this — the button
          above is the normal way to generate a website.
        </p>
        <div className="generations-panel__form">
          <select value={advancedType} onChange={(event) => setAdvancedType(event.target.value as CreativeGenerationType)}>
            {ADVANCED_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type} disabled={providers != null && !supportedTypes.has(type)}>
                {type}
                {providers != null && !supportedTypes.has(type) ? " (no available provider)" : ""}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => handleGenerate(advancedType)}
            disabled={isGenerating || (providers != null && !supportedTypes.has(advancedType))}
          >
            {isGenerating ? "Generating…" : "Generate"}
          </button>
        </div>
      </details>
    </div>
  );
}
