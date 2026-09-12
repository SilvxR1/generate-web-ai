import { useEffect, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import {
  API_URL,
  createCreativeDirections,
  createGenerativeWebsiteDraft,
  getFrontendEngineerAvailability,
  getGenerativeArtifact,
  runGenerativeVisualQa,
  type CreativeDirection,
  type FrontendEngineerAvailability,
  type GenerativeArtifact,
  type WebsiteDraft,
  type WebsiteState,
} from "../../lib/api";

interface GenerativeWorkflowPanelProps {
  businessId: string;
  tenantId: string;
  /** Every WebsiteDraft this business has ever produced via the AI
   * Frontend Engineer (engine === "generative"), most recent first —
   * the deterministic engine's own drafts live entirely in
   * WebsiteDraftsPanel; the two tracks are never mixed. */
  generativeDrafts: WebsiteDraft[];
  onDraftCreated: (draft: WebsiteDraft) => void;
  onApprove: (draftId: string) => Promise<WebsiteDraft>;
  onPublish: (draftId: string) => Promise<WebsiteState>;
}

/** Every state a real generative pipeline run can be in, shown to a
 * human — never a raw backend status string (e.g. "build_failed") or
 * provider enum. Kept as an explicit, ordered list because P2's own
 * acceptance criteria names these exact six stages. */
type PipelineStage =
  | "CREATIVE_DIRECTION_READY"
  | "FRONTEND_GENERATING"
  | "BUILDING"
  | "QA_RUNNING"
  | "PREVIEW_READY"
  | "FAILED";

const STAGE_LABELS: Record<PipelineStage, string> = {
  CREATIVE_DIRECTION_READY: "Creative direction selected — ready to generate",
  FRONTEND_GENERATING: "Generating your website with AI…",
  BUILDING: "Building and validating your website…",
  QA_RUNNING: "Running real-browser visual quality checks…",
  PREVIEW_READY: "Preview ready",
  FAILED: "Generation failed",
};

function StageBanner({ stage, detail }: { stage: PipelineStage; detail?: string }) {
  const kind = stage === "FAILED" ? "banner--error" : stage === "PREVIEW_READY" ? "banner--ok" : "banner--warning";
  return (
    <p className={`banner ${kind}`}>
      <strong>{STAGE_LABELS[stage]}</strong>
      {detail ? ` — ${detail}` : ""}
    </p>
  );
}

/** Business → Assets → Creative Direction → AI Frontend Engineer →
 * real build → Visual QA → preview (P2 continuation Part 5). Entirely
 * separate from the deterministic generateSiteConfig() track above —
 * neither replaces the other; a business can use either, and this
 * panel never touches a deterministic draft. */
export function GenerativeWorkflowPanel({
  businessId,
  tenantId,
  generativeDrafts,
  onDraftCreated,
  onApprove,
  onPublish,
}: GenerativeWorkflowPanelProps) {
  const [availability, setAvailability] = useState<FrontendEngineerAvailability | null>(null);
  const [availabilityError, setAvailabilityError] = useState<string | null>(null);

  const [directions, setDirections] = useState<CreativeDirection[]>([]);
  const [directionsLoaded, setDirectionsLoaded] = useState(false);
  const [selectedDirectionId, setSelectedDirectionId] = useState<string | null>(null);
  const [isGeneratingDirections, setIsGeneratingDirections] = useState(false);
  const [directionsError, setDirectionsError] = useState<string | null>(null);

  const [isGeneratingWebsite, setIsGeneratingWebsite] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const [artifact, setArtifact] = useState<GenerativeArtifact | null>(null);
  const [isRunningQa, setIsRunningQa] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);

  const activeDraft = generativeDrafts[0] ?? null;

  useEffect(() => {
    let cancelled = false;
    getFrontendEngineerAvailability(businessId, tenantId)
      .then((data) => !cancelled && setAvailability(data))
      .catch((error: unknown) => !cancelled && setAvailabilityError(friendlyErrorMessage(error, "Unknown error")));
    return () => {
      cancelled = true;
    };
  }, [businessId, tenantId]);

  // Once a draft exists and finished building, load its QA record so a
  // page refresh (or simply reopening this section) shows real state
  // instead of resetting to "no artifact yet".
  const activeDraftId = activeDraft?.id ?? null;
  const activeDraftStatus = activeDraft?.status ?? null;
  useEffect(() => {
    if (!activeDraftId || activeDraftStatus === "build_failed" || activeDraftStatus === "draft") {
      setArtifact(null);
      return;
    }
    let cancelled = false;
    getGenerativeArtifact(businessId, activeDraftId, tenantId)
      .then((data) => !cancelled && setArtifact(data))
      .catch(() => !cancelled && setArtifact(null));
    return () => {
      cancelled = true;
    };
  }, [businessId, activeDraftId, activeDraftStatus, tenantId]);

  async function handleGenerateDirections() {
    setIsGeneratingDirections(true);
    setDirectionsError(null);
    try {
      const created = await createCreativeDirections(businessId, tenantId);
      setDirections(created);
      setDirectionsLoaded(true);
      const recommended = created.find((direction) => direction.is_recommended);
      setSelectedDirectionId(recommended?.id ?? created[0]?.id ?? null);
    } catch (error) {
      setDirectionsError(friendlyErrorMessage(error, "Could not generate creative directions."));
    } finally {
      setIsGeneratingDirections(false);
    }
  }

  async function handleGenerateWebsite() {
    if (!selectedDirectionId) return;
    setIsGeneratingWebsite(true);
    setGenerateError(null);
    setArtifact(null);
    try {
      const draft = await createGenerativeWebsiteDraft(businessId, selectedDirectionId, tenantId);
      onDraftCreated(draft);
    } catch (error) {
      setGenerateError(friendlyErrorMessage(error, "Could not generate a website from this direction."));
    } finally {
      setIsGeneratingWebsite(false);
    }
  }

  async function handleRunVisualQa() {
    if (!activeDraft) return;
    setIsRunningQa(true);
    setQaError(null);
    try {
      const result = await runGenerativeVisualQa(businessId, activeDraft.id, tenantId);
      setArtifact(result);
    } catch (error) {
      setQaError(friendlyErrorMessage(error, "Visual QA failed to run."));
    } finally {
      setIsRunningQa(false);
    }
  }

  let stage: PipelineStage | null = null;
  let stageDetail: string | undefined;
  if (isGeneratingWebsite) {
    stage = "FRONTEND_GENERATING";
  } else if (isRunningQa) {
    stage = "QA_RUNNING";
  } else if (activeDraft?.status === "build_failed") {
    stage = "FAILED";
    stageDetail = activeDraft.build_error ?? undefined;
  } else if (activeDraft && artifact?.visual_qa_state && Object.keys(artifact.visual_qa_state).length > 0) {
    stage = "PREVIEW_READY";
    stageDetail = artifact.visual_qa_state.passed === false ? "Visual QA found issues — see below." : undefined;
  } else if (activeDraft && (activeDraft.status === "ready" || activeDraft.status === "approved" || activeDraft.status === "published")) {
    stage = "BUILDING";
    stageDetail = "Build succeeded — run visual QA to see a real preview.";
  } else if (selectedDirectionId) {
    stage = "CREATIVE_DIRECTION_READY";
  }

  return (
    <div className="generative-workflow-panel">
      <p className="field-hint">
        A different way to build this business's website: an AI Frontend Engineer writes real, bespoke source code
        from a chosen creative direction instead of assembling pre-built page blocks. This never affects the
        deterministic generation above.
      </p>

      {availabilityError && <p className="banner banner--error">Could not check AI availability: {availabilityError}</p>}
      {availability && !availability.available && (
        <p className="banner banner--warning">
          AI website generation is currently unavailable: {availability.unavailable_reason}
        </p>
      )}

      <div className="generative-workflow-panel__directions">
        <button
          type="button"
          onClick={handleGenerateDirections}
          disabled={isGeneratingDirections || (availability != null && !availability.available)}
        >
          {isGeneratingDirections
            ? "Generating creative directions…"
            : directionsLoaded
              ? "Regenerate creative directions"
              : "Generate creative directions"}
        </button>
        {directionsError && <p className="banner banner--error">{directionsError}</p>}

        {directions.length > 0 && (
          <ul className="generative-workflow-panel__direction-list">
            {directions.map((direction) => {
              const isSelected = direction.id === selectedDirectionId;
              return (
                <li
                  key={direction.id}
                  className="generative-workflow-panel__direction-card"
                  style={{ border: isSelected ? "2px solid currentColor" : "1px solid transparent" }}
                >
                  <div>
                    <strong>{direction.concept.name}</strong>
                    {direction.is_recommended && " · Recommended"}
                  </div>
                  <p className="field-hint">{direction.concept.rationale}</p>
                  {direction.selection_rationale && <p className="field-hint">Why: {direction.selection_rationale}</p>}
                  {direction.credits_used != null && (
                    <p className="field-hint">{direction.credits_used} Higgsfield credits used</p>
                  )}
                  <button type="button" onClick={() => setSelectedDirectionId(direction.id)} disabled={isSelected}>
                    {isSelected ? "Selected" : direction.is_recommended ? "Use recommended" : "Choose this direction"}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="generative-workflow-panel__generate">
        <button type="button" onClick={handleGenerateWebsite} disabled={!selectedDirectionId || isGeneratingWebsite}>
          {isGeneratingWebsite ? "Generating website…" : "Generate website"}
        </button>
        {generateError && <p className="banner banner--error">{generateError}</p>}
      </div>

      {stage && <StageBanner stage={stage} detail={stageDetail} />}

      {activeDraft?.validation_issues && activeDraft.validation_issues.length > 0 && (
        <ul className="generative-workflow-panel__issues">
          {activeDraft.validation_issues.map((issue) => (
            <li key={issue} className="field-hint">
              ⚠ {issue}
            </li>
          ))}
        </ul>
      )}

      {activeDraft && activeDraft.status === "ready" && (
        <div className="generative-workflow-panel__qa">
          <button type="button" onClick={handleRunVisualQa} disabled={isRunningQa}>
            {isRunningQa ? "Running visual QA…" : "Run visual QA"}
          </button>
          {qaError && <p className="banner banner--error">{qaError}</p>}
        </div>
      )}

      {artifact && Object.keys(artifact.screenshot_urls).length > 0 && (
        <div className="generative-workflow-panel__preview">
          <h4>Real preview</h4>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            {Object.entries(artifact.screenshot_urls).map(([viewport, url]) => (
              <figure key={viewport}>
                <img src={`${API_URL}${url}`} alt={`${viewport} preview`} style={{ maxWidth: "280px" }} />
                <figcaption className="field-hint">{viewport}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}

      {activeDraft && (activeDraft.status === "ready" || activeDraft.status === "approved") && (
        <div className="generative-workflow-panel__actions">
          {activeDraft.status === "ready" && (
            <button type="button" onClick={() => onApprove(activeDraft.id)}>
              Approve
            </button>
          )}
          {activeDraft.status === "approved" && (
            <button type="button" onClick={() => onPublish(activeDraft.id)}>
              Publish
            </button>
          )}
        </div>
      )}
      {activeDraft?.status === "published" && <p className="field-hint">Published from this generative draft.</p>}
    </div>
  );
}
