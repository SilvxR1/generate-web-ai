import type { SiteConfig } from "@generate-web-ai/site-config";
import { useRef, useState } from "react";
import { ErrorBanner } from "../business-analysis/ErrorBanner";
import { categorizePublishError, friendlyErrorMessage, type CategorizedError } from "../business-analysis/errors";
import {
  ApiError,
  type CustomDomainState,
  type WebsiteDraft,
  type WebsiteDraftPreview,
  type WebsiteState,
} from "../../lib/api";
import { RealPreviewAction } from "./RealPreviewAction";

interface WebsitePublishProps {
  /** The exact SiteConfig the Content summary renders — the draft is
   * built from this same object, never a value this component recomputes. */
  siteConfig: SiteConfig | null;
  /** The business's *persisted* deployment state (backend's
   * app.db.models.website.Website, loaded fresh whenever the preview
   * step opens) — the source of truth for Published/Preview. Never
   * inferred from this component's own past actions. */
  websiteState: WebsiteState | null;
  isLoadingWebsiteState: boolean;
  /** The business's *persisted* custom-domain state (LR-04) — used only
   * to decide whether the Cloudflare `*.pages.dev` URL below should be
   * labeled a technical preview URL (no active custom domain yet) or a
   * fallback next to the real production domain (one is active). Never
   * used to gate publishing itself — a custom domain is optional. */
  customDomain: CustomDomainState | null;
  /** POST .../website-drafts — builds the site ONCE and stores it. Never publishes. */
  onCreateDraft: (siteConfig: SiteConfig) => Promise<WebsiteDraft>;
  /** POST .../website-drafts/{id}/preview — the real built website, new tab. */
  onPreview: (draftId: string) => Promise<WebsiteDraftPreview>;
  /** POST .../website-drafts/{id}/approve — explicit "Use this design". */
  onApprove: (draftId: string) => Promise<WebsiteDraft>;
  /** POST .../website-drafts/{id}/publish — promotes the approved draft's exact stored website. */
  onPublish: (draftId: string) => Promise<WebsiteState>;
}

const BUILD_FAILED_MESSAGE = "We couldn't build this website. Nothing was published.";
const CREATE_FAILED_MESSAGE = "We couldn't prepare this website. Please try again. Nothing was published.";

// Local, ephemeral UI feedback only — never the source of truth for
// whether the site is published (that's always `websiteState`, reread
// from the backend).
type Pending = "creating" | "approving" | "publishing" | null;

/** Draft publish failures: a draft whose stored website can't be used
 * must be regenerated — its storage details are never shown. */
function publishError(error: unknown): CategorizedError {
  if (error instanceof ApiError && error.code.startsWith("website_draft_artifact")) {
    return {
      category: "publish_failed",
      title: "This website needs to be generated again",
      message: "Nothing was published. Generate the website again, preview it and publish.",
    };
  }
  return categorizePublishError(error);
}

/** A8.4 — the first website (and any later content update) goes live
 * through the SAME WebsiteDraft lifecycle as a redesign: Generate website
 * (one build, stored) -> Open real preview -> Use this design -> Publish,
 * which promotes the exact previewed bytes. There is no direct
 * SiteConfig publish here anymore (the legacy POST .../website/publish). */
export function WebsitePublish({
  siteConfig,
  websiteState,
  isLoadingWebsiteState,
  customDomain,
  onCreateDraft,
  onPreview,
  onApprove,
  onPublish,
}: WebsitePublishProps) {
  const [draft, setDraft] = useState<WebsiteDraft | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [confirming, setConfirming] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [failedPublish, setFailedPublish] = useState<CategorizedError | null>(null);
  // A second click in the same frame must not start a second build.
  const inFlight = useRef(false);

  if (isLoadingWebsiteState) {
    return <p>Loading publish status…</p>;
  }
  if (!siteConfig) {
    return null;
  }

  const isPublished = websiteState?.status === "live" && !!websiteState.live_url;
  const hasActiveDomain = customDomain?.status === "active";

  async function run(kind: Exclude<Pending, null>, action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(kind);
    try {
      await action();
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }

  function handleGenerate() {
    return run("creating", async () => {
      setCreateError(null);
      setApproveError(null);
      setFailedPublish(null);
      setConfirming(false);
      try {
        setDraft(await onCreateDraft(siteConfig as SiteConfig));
      } catch {
        setCreateError(CREATE_FAILED_MESSAGE);
      }
    });
  }

  function handleApprove(current: WebsiteDraft) {
    return run("approving", async () => {
      setApproveError(null);
      try {
        setDraft(await onApprove(current.id));
      } catch (caught) {
        setApproveError(friendlyErrorMessage(caught, "Could not approve this website."));
      }
    });
  }

  function handlePublish(current: WebsiteDraft) {
    return run("publishing", async () => {
      setFailedPublish(null);
      try {
        await onPublish(current.id);
        setDraft(null);
        setConfirming(false);
      } catch (caught) {
        setFailedPublish(publishError(caught));
      }
    });
  }

  const previewable = draft !== null && (draft.status === "ready" || draft.status === "approved");

  return (
    <div className="website-publish">
      {isPublished && !draft && (
        <>
          <p className="banner banner--ok">Published — this website is live.</p>

          {hasActiveDomain ? (
            <>
              <p>
                <strong>Production domain:</strong>{" "}
                <a href={`https://${customDomain!.domain}`} target="_blank" rel="noreferrer noopener">
                  {customDomain!.domain}
                </a>
              </p>
              <p className="field-hint">
                Technical/preview URL (still works, but not the address to share with customers):{" "}
                <a href={websiteState!.live_url!} target="_blank" rel="noreferrer noopener">
                  {websiteState!.live_url}
                </a>
              </p>
            </>
          ) : (
            <>
              <a className="button" href={websiteState!.live_url!} target="_blank" rel="noreferrer noopener">
                Open live website
              </a>
              <p className="field-hint">
                This is a temporary technical URL ({websiteState!.live_url}), not the address a customer would expect.
                If this business already owns a domain (e.g. "yourbusiness.com"), connect it in the{" "}
                <a href="#custom-domain-section">Custom domain</a> section below — otherwise it's fine to configure
                that later.
              </p>
            </>
          )}
        </>
      )}

      {(!draft || draft.status === "build_failed") && (
        <>
          {!isPublished && (
            <p className="field-hint">
              Generating builds the real website so you can preview it. Nothing goes live until you publish.
            </p>
          )}
          <button type="button" onClick={handleGenerate} disabled={pending === "creating"} aria-busy={pending === "creating"}>
            {pending === "creating"
              ? "Building website…"
              : isPublished
                ? "Prepare an update from current content"
                : "Generate website"}
          </button>
          {createError && (
            <p className="banner banner--error" role="alert">
              {createError}
            </p>
          )}
          {draft?.status === "build_failed" && (
            <div className="banner banner--error" role="alert">
              <p>{BUILD_FAILED_MESSAGE}</p>
              {draft.build_error && (
                <details className="banner__detail">
                  <summary>Technical details</summary>
                  <code>{draft.build_error}</code>
                </details>
              )}
            </div>
          )}
        </>
      )}

      {previewable && draft && (
        <div className="website-publish__draft">
          <p className="banner banner--warning" role="status">
            <strong>{draft.status === "approved" ? "Approved — not published yet." : "Ready to review."}</strong>{" "}
            {isPublished ? "Your live website has not changed." : "Nothing is live yet."}
          </p>
          <RealPreviewAction requestPreview={() => onPreview(draft.id)} />

          {approveError && <p className="banner banner--error">{approveError}</p>}

          {draft.status === "ready" && (
            <button
              type="button"
              onClick={() => handleApprove(draft)}
              disabled={pending === "approving"}
              aria-busy={pending === "approving"}
            >
              {pending === "approving" ? "Approving…" : "Use this design"}
            </button>
          )}

          {draft.status === "approved" && !confirming && pending !== "publishing" && !failedPublish && (
            <button type="button" onClick={() => setConfirming(true)}>
              Publish website
            </button>
          )}

          {draft.status === "approved" && confirming && pending !== "publishing" && !failedPublish && (
            <div className="publish-confirm">
              <p className="banner__title">Confirm publication</p>
              <p className="activation-confirm__warning">
                This will make exactly the website you previewed publicly reachable at a live URL
                {isPublished ? ", replacing the current one" : ""}.
              </p>
              <div className="proposal-actions">
                <button type="button" onClick={() => setConfirming(false)}>
                  Cancel
                </button>
                <button type="button" onClick={() => handlePublish(draft)}>
                  Confirm publish
                </button>
              </div>
            </div>
          )}

          {pending === "publishing" && <p>Publishing…</p>}

          {failedPublish && pending !== "publishing" && (
            <>
              <ErrorBanner error={failedPublish} />
              <button type="button" onClick={() => handlePublish(draft)}>
                Try again
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
