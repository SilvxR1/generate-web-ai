import { validateWebsiteCreativeDirection } from "@generate-web-ai/site-config";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import {
  ApiError,
  approveWebsiteDraft,
  createCreativeGeneration,
  createWebsiteDraft,
  publishWebsiteDraft,
  type BusinessAsset,
  type CreatedBusiness,
  type WebsiteDraft,
  type WebsiteState,
} from "../../lib/api";
import { SiteConfigPreview } from "../business-preview/SiteConfigPreview";

type Direction = "evolve" | "new_direction";
type Step = "intent" | "confirm" | "generating" | "proposal" | "error";

const BUILD_FAILED_MESSAGE = "We couldn't build this proposal. Your live website has not changed.";
const DIRECTION_MISSING_MESSAGE =
  "We couldn't create a design direction for this proposal. Please try again. Your live website has not changed.";

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
 * first (what kind of change), safe defaults second: the primary path
 * here always requests CreativeLevel.BASIC and BrandStrategy EVOLVE/
 * NEW_DIRECTION as PER-REQUEST overrides on POST .../creative-generations
 * (app.creative.orchestrator.orchestrate_generation's own brand_strategy/
 * creative_level parameters — never written back to the business's own
 * persisted CreativeConfig, so a redesign experiment never silently
 * redefines the business's standing brand policy or generation tier).
 * app.creative.orchestrator never requires a premium provider at BASIC —
 * see app.domain.business_config.creative.CreativeConfig's own default —
 * so this always resolves through the deterministic/internal engine
 * (app.creative.internal), the same free, always-available path
 * GenerationsPanel's "Generate website" already uses — never CINEMATIC/
 * PREMIUM, and never Higgsfield, regardless of which direction the user
 * picks.
 *
 * There is deliberately no free-text "describe the style you want" input
 * here: app.domain.creative.brief.build_creative_brief (the one place a
 * CreativeBrief is assembled, for every provider including Higgsfield)
 * has no parameter that consumes arbitrary text — only the enum-valued
 * brand_strategy/creative_level above. A textarea a user could type into
 * without it affecting the result would be misleading UI, not a real
 * feature, so this flow only offers the two real, honored inputs.
 *
 * Generate -> Preview -> Approve -> Publish is preserved exactly:
 * everything before handlePublish below only ever calls read/propose
 * endpoints (creative-generations, website-drafts, approve) — none of
 * which touch the live website. Only handlePublish calls POST
 * .../website-drafts/{id}/publish, the one call that can change
 * production. */
export function RedesignFlow({ business, tenantId, assets, onPublished, onClose }: RedesignFlowProps) {
  const [step, setStep] = useState<Step>("intent");
  const [direction, setDirection] = useState<Direction | null>(null);
  const [draft, setDraft] = useState<WebsiteDraft | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [isPublishing, setIsPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!direction) return;
    if (!business.config) {
      setErrorMessage("This business's profile isn't complete yet — finish the business profile first.");
      setStep("error");
      return;
    }
    setIsGenerating(true);
    setErrorMessage(null);
    setErrorDetail(null);
    try {
      const generation = await createCreativeGeneration(business.id, "website", tenantId, {
        brandStrategy: direction,
        creativeLevel: "basic",
      });
      if (generation.status !== "completed") {
        setErrorMessage(BUILD_FAILED_MESSAGE);
        setStep("error");
        return;
      }

      // A8.2.3: the proposal is built from the exact normalized direction
      // this generation recorded (one generation = one stored direction =
      // one proposal), never re-derived here. A missing/invalid one is an
      // explicit error: falling back to the undirected build would show the
      // same site for every choice again.
      const storedDirection = generation.website_direction ?? null;
      const checked = storedDirection ? validateWebsiteCreativeDirection(storedDirection) : null;
      if (!checked?.ok) {
        setErrorMessage(DIRECTION_MISSING_MESSAGE);
        setErrorDetail(
          checked
            ? `Creative generation ${generation.id} returned an invalid website_direction: ${checked.errors.join("; ")}`
            : `Creative generation ${generation.id} returned no website_direction.`,
        );
        setStep("error");
        return;
      }

      const siteConfig = generateSiteConfig(business.config, assets, checked.value);
      const newDraft = await createWebsiteDraft(business.id, siteConfig, generation.id, tenantId);
      setDraft(newDraft);
      setStep("proposal");
    } catch (caught) {
      // A backend rejection's own message is implementation detail (e.g.
      // a validation error) — kept for operators under Technical
      // details, never the owner's primary message.
      if (caught instanceof ApiError) {
        setErrorMessage(BUILD_FAILED_MESSAGE);
        setErrorDetail(`${caught.code}: ${caught.message}`);
      } else {
        setErrorMessage(
          friendlyErrorMessage(caught, "Something went wrong generating this proposal. Your live website has not changed."),
        );
      }
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
            <button type="button" disabled={!direction} onClick={() => setStep("confirm")}>
              Continue
            </button>
          </div>
        </div>
      )}

      {step === "confirm" && direction && (
        <div className="redesign-flow__style">
          <h3>Review and generate</h3>

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

          <div className="redesign-flow__summary">
            <h4>Redesign</h4>
            <dl>
              <dt>Direction</dt>
              <dd>{direction === "evolve" ? "Refresh the current design" : "Create a new design direction"}</dd>
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
          <div className="banner banner--error" role="alert">
            <p>{errorMessage}</p>
            {errorDetail && (
              <details className="banner__detail">
                <summary>Technical details</summary>
                <code>{errorDetail}</code>
              </details>
            )}
          </div>
          <div className="redesign-flow__actions">
            <button type="button" onClick={onClose}>
              Close
            </button>
            <button type="button" onClick={() => setStep("confirm")}>
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
            <p className="banner banner--error">{BUILD_FAILED_MESSAGE}</p>
          )}

          {draft.status === "build_failed" && (
            <div className="banner banner--error" role="alert">
              <p>{BUILD_FAILED_MESSAGE}</p>
              {/* The raw build/PlatformContract error stays available for
               * operators, but never as the owner's primary message. */}
              {draft.build_error && (
                <details className="banner__detail">
                  <summary>Technical details</summary>
                  <code>{draft.build_error}</code>
                </details>
              )}
            </div>
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
