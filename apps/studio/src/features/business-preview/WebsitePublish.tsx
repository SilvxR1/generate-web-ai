import type { SiteConfig } from "@generate-web-ai/site-config";
import { useState } from "react";
import { ErrorBanner } from "../business-analysis/ErrorBanner";
import { categorizePublishError, type CategorizedError } from "../business-analysis/errors";
import type { WebsiteState } from "../../lib/api";

interface WebsitePublishProps {
  /** The exact SiteConfig SiteConfigPreview is rendering — publish sends
   * this same object, never a value this component recomputes itself. */
  siteConfig: SiteConfig | null;
  /** The business's *persisted* deployment state (backend's
   * app.db.models.website.Website, loaded fresh whenever the preview
   * step opens) — the source of truth for Published/Preview. Never
   * inferred from this component's own past actions. */
  websiteState: WebsiteState | null;
  isLoadingWebsiteState: boolean;
  onPublish: (siteConfig: SiteConfig) => Promise<WebsiteState>;
}

// Local, ephemeral UI feedback only — never the source of truth for
// whether the site is published (that's always `websiteState`, reread
// from the backend). "confirming" is the pre-publish confirmation step;
// "publishing" covers the in-flight request; "failed" is the last
// attempt's outcome, cleared as soon as another attempt starts.
type UiState = { kind: "idle" } | { kind: "confirming" } | { kind: "publishing" } | { kind: "failed"; error: CategorizedError };

export function WebsitePublish({ siteConfig, websiteState, isLoadingWebsiteState, onPublish }: WebsitePublishProps) {
  const [ui, setUi] = useState<UiState>({ kind: "idle" });

  if (isLoadingWebsiteState) {
    return <p>Loading publish status…</p>;
  }
  if (!siteConfig) {
    return null;
  }

  const isPublished = websiteState?.status === "live" && !!websiteState.live_url;

  async function handleConfirmPublish() {
    setUi({ kind: "publishing" });
    try {
      await onPublish(siteConfig as SiteConfig);
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "failed", error: categorizePublishError(caught) });
    }
  }

  return (
    <div className="website-publish">
      {ui.kind === "publishing" && <p>Publishing…</p>}

      {ui.kind === "failed" && (
        <>
          <ErrorBanner error={ui.error} />
          <button type="button" onClick={handleConfirmPublish}>
            Try again
          </button>
        </>
      )}

      {ui.kind === "idle" && isPublished && (
        <>
          <p className="banner banner--ok">Published — this website is live.</p>
          <a className="button" href={websiteState!.live_url!} target="_blank" rel="noreferrer noopener">
            Open live website
          </a>
          <button type="button" onClick={() => setUi({ kind: "confirming" })}>
            Publish again
          </button>
        </>
      )}

      {ui.kind === "idle" && !isPublished && (
        <button type="button" onClick={() => setUi({ kind: "confirming" })}>
          Publish website
        </button>
      )}

      {ui.kind === "confirming" && (
        <div className="publish-confirm">
          <p className="banner__title">Confirm publication</p>
          <p className="activation-confirm__warning">
            This will make this business's website publicly reachable at a live URL, using the content shown in the
            preview above. Make sure it's ready before continuing.
          </p>
          <div className="proposal-actions">
            <button type="button" onClick={() => setUi({ kind: "idle" })}>
              Cancel
            </button>
            <button type="button" onClick={handleConfirmPublish}>
              Confirm publish
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
