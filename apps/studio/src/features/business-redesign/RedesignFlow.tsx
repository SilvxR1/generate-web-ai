import type { CreativeConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { useEffect, useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import {
  approveWebsiteDraft,
  createCreativeGeneration,
  createWebsiteDraft,
  listCreativeProviders,
  publishWebsiteDraft,
  updateCreativeConfig,
  type BusinessAsset,
  type CreatedBusiness,
  type CreativeProviderAvailability,
  type WebsiteDraft,
  type WebsiteState,
} from "../../lib/api";
import { SiteConfigPreview } from "../business-preview/SiteConfigPreview";

type Direction = "evolve" | "new_direction";
type Step = "intent" | "style" | "generating" | "proposal" | "error";

interface RedesignFlowProps {
  business: CreatedBusiness;
  tenantId: string;
  /** The business's real, already-uploaded assets — the same list
   * PreviewStep's own live preview and publish already use (LR-05).
   * Never a separate/parallel fetch, so a redesign proposal always
   * reflects the same real logo/photos the current live site does. */
  assets: BusinessAsset[];
  onPublished: (state: WebsiteState) => void;
  onClose: () => void;
}

/** A8.1 — the one obvious "redesign this website" entry point. Intent
 * first (what kind of change, then optionally what style), safe
 * defaults second: the primary path here always requests
 * CreativeLevel.BASIC (app.creative.orchestrator never requires a
 * premium provider at that level — see app.domain.business_config.
 * creative.CreativeConfig's own default) and the deterministic/internal
 * engine (app.creative.internal), the same free, always-available path
 * GenerationsPanel's "Generate website" already uses — never CINEMATIC/
 * PREMIUM, and never Higgsfield, regardless of which direction the user
 * picks. Brand-change intent (this component's own A/B choice) and
 * paid-generation tier are deliberately kept separate, per A8.1 Section 6.
 *
 * Generate -> Preview -> Approve -> Publish is preserved exactly:
 * everything before handlePublish below only ever calls read/propose
 * endpoints (creative-config, creative-generations, website-drafts,
 * approve) — none of which touch the live website. Only handlePublish
 * calls POST .../website-drafts/{id}/publish, the one call that can
 * change production. */
export function RedesignFlow({ business, tenantId, assets, onPublished, onClose }: RedesignFlowProps) {
  const [step, setStep] = useState<Step>("intent");
  const [direction, setDirection] = useState<Direction | null>(null);
  const [style, setStyle] = useState("");
  const [draft, setDraft] = useState<WebsiteDraft | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  // Fetched independently, only while this flow is open — same lazy-load
  // convention CreativeSection already uses — purely to give an honest
  // "AI-generated premium visuals aren't available right now" message.
  // This flow never sends a request that would actually invoke Higgsfield:
  // it only ever requests CreativeLevel.BASIC (see handleGenerate below).
  const [providers, setProviders] = useState<CreativeProviderAvailability[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCreativeProviders(business.id, tenantId)
      .then((data) => {
        if (!cancelled) setProviders(data);
      })
      .catch(() => {
        if (!cancelled) setProviders(null);
      });
    return () => {
      cancelled = true;
    };
  }, [business.id, tenantId]);

  const higgsfield = providers?.find((provider) => provider.provider === "higgsfield") ?? null;
  const aiVisualsAvailable = higgsfield?.available === true;

  async function handleGenerate() {
    if (!direction) return;
    if (!business.config) {
      setErrorMessage("This business's profile isn't complete yet — finish the business profile first.");
      setStep("error");
      return;
    }
    setIsGenerating(true);
    setErrorMessage(null);
    try {
      const config: CreativeConfig = { strategy: direction, level: "basic", preferred_provider: null };
      await updateCreativeConfig(business.id, config, tenantId);

      const generation = await createCreativeGeneration(business.id, "website", tenantId);
      if (generation.status !== "completed") {
        setErrorMessage("We couldn't build this proposal. Your live website has not changed.");
        setStep("error");
        return;
      }

      const siteConfig = generateSiteConfig(business.config, assets);
      const newDraft = await createWebsiteDraft(business.id, siteConfig, generation.id, tenantId);
      setDraft(newDraft);
      setStep("proposal");
    } catch (caught) {
      setErrorMessage(
        friendlyErrorMessage(caught, "Something went wrong generating this proposal. Your live website has not changed."),
      );
      setStep("error");
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleApprove() {
    if (!draft) return;
    setIsApproving(true);
    setApproveError(null);
    try {
      const updated = await approveWebsiteDraft(business.id, draft.id, tenantId);
      setDraft(updated);
    } catch (caught) {
      setApproveError(friendlyErrorMessage(caught, "Could not approve this proposal."));
    } finally {
      setIsApproving(false);
    }
  }

  async function handlePublish() {
    if (!draft) return;
    setIsPublishing(true);
    setPublishError(null);
    try {
      const state = await publishWebsiteDraft(business.id, draft.id, tenantId);
      onPublished(state);
    } catch (caught) {
      setPublishError(
        friendlyErrorMessage(caught, "Could not publish this proposal. Your live website has not changed."),
      );
    } finally {
      setIsPublishing(false);
    }
  }

  return (
    <div className="redesign-flow">
      {step === "intent" && (
        <div className="redesign-flow__intent">
          <h3>What do you want to change?</h3>
          <div className="redesign-flow__choices">
            <button
              type="button"
              className={direction === "evolve" ? "redesign-flow__choice redesign-flow__choice--selected" : "redesign-flow__choice"}
              onClick={() => setDirection("evolve")}
            >
              <strong>Refresh the current design</strong>
              <span>Keep the existing brand identity and content while improving the visual presentation.</span>
            </button>
            <button
              type="button"
              className={
                direction === "new_direction" ? "redesign-flow__choice redesign-flow__choice--selected" : "redesign-flow__choice"
              }
              onClick={() => setDirection("new_direction")}
            >
              <strong>Create a new design direction</strong>
              <span>Explore a substantially different visual direction while preserving factual business information and real customer assets.</span>
            </button>
          </div>
          <div className="redesign-flow__actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button type="button" disabled={!direction} onClick={() => setStep("style")}>
              Continue
            </button>
          </div>
        </div>
      )}

      {step === "style" && direction && (
        <div className="redesign-flow__style">
          <h3>Describe the style you want (optional)</h3>
          <textarea
            value={style}
            onChange={(event) => setStyle(event.target.value)}
            placeholder="e.g. modern, minimal, premium, warm, editorial, playful, elegant…"
            rows={3}
            aria-label="Describe the style you want"
          />

          <div className="redesign-flow__preserve">
            <p>
              <strong>Keeping</strong>
            </p>
            <ul>
              <li>✓ Your real business information</li>
              <li>✓ Your real logo</li>
              <li>✓ Your real photographs</li>
            </ul>
          </div>

          <div className="redesign-flow__ai-visuals">
            <strong>AI-generated premium visuals</strong>{" "}
            <span className="field-hint">
              {aiVisualsAvailable
                ? "Available as an advanced enhancement — not used by this proposal."
                : "AI-generated premium visuals aren't available right now. This proposal will continue without them."}
            </span>
          </div>

          <div className="redesign-flow__summary">
            <h4>Redesign</h4>
            <dl>
              <dt>Direction</dt>
              <dd>{direction === "evolve" ? "Refresh the current design" : "Create a new design direction"}</dd>
              {style.trim() && (
                <>
                  <dt>Style</dt>
                  <dd>"{style.trim()}"</dd>
                </>
              )}
              <dt>Keeping</dt>
              <dd>Business information, logo, and real photographs</dd>
              <dt>AI-generated premium visuals</dt>
              <dd>Off</dd>
            </dl>
          </div>

          <div className="redesign-flow__actions">
            <button type="button" onClick={() => setStep("intent")} disabled={isGenerating}>
              Back
            </button>
            <button type="button" onClick={handleGenerate} disabled={isGenerating}>
              {isGenerating ? "Generating proposal…" : "Generate proposal"}
            </button>
          </div>
        </div>
      )}

      {step === "generating" && <p className="field-hint">Generating proposal…</p>}

      {step === "error" && (
        <div className="redesign-flow__error">
          <p className="banner banner--error">{errorMessage}</p>
          <div className="redesign-flow__actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
            <button type="button" onClick={() => setStep("style")}>
              Try again
            </button>
          </div>
        </div>
      )}

      {step === "proposal" && draft && (
        <div className="redesign-flow__proposal">
          <h3>Proposal preview</h3>
          <p className="field-hint">This is a preview only — your live website has not changed.</p>

          {draft.site_config ? (
            <SiteConfigPreview siteConfig={draft.site_config} />
          ) : (
            <p className="banner banner--error">We couldn't build this proposal. Your live website has not changed.</p>
          )}

          {draft.status === "build_failed" && (
            <p className="banner banner--error">
              We couldn't build this proposal. Your live website has not changed.
              {draft.build_error ? ` (${draft.build_error})` : ""}
            </p>
          )}

          {approveError && <p className="banner banner--error">{approveError}</p>}
          {publishError && <p className="banner banner--error">{publishError}</p>}

          <div className="redesign-flow__actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
            {draft.status !== "approved" && draft.status !== "published" && (
              <button type="button" onClick={handleApprove} disabled={isApproving || draft.status !== "ready"}>
                {isApproving ? "Approving…" : "Use this design"}
              </button>
            )}
            {(draft.status === "approved" || draft.status === "published") && (
              <>
                <p className="field-hint">Your current website is still live. Publishing will replace it with this design.</p>
                <button
                  type="button"
                  onClick={handlePublish}
                  disabled={isPublishing || draft.status === "published"}
                >
                  {isPublishing ? "Publishing…" : draft.status === "published" ? "Published" : "Publish"}
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
