import { useRef, useState } from "react";
import type { WebsiteDraftPreview } from "../../lib/api";
import {
  PREVIEW_UNAVAILABLE_MESSAGE,
  REAL_PREVIEW_NOTICE,
  closePendingTab,
  navigatePendingTab,
  openPendingTab,
  previewErrorMessage,
  safePreviewUrl,
} from "./realPreview";

interface RealPreviewActionProps {
  /** POST .../website-drafts/{id}/preview — deploys or reuses the draft's
   * exact built website. Never approves, never publishes. */
  requestPreview: () => Promise<WebsiteDraftPreview>;
  /** Show the short explanation under the button (off where a parent
   * already shows it once, e.g. a list of drafts). */
  showNotice?: boolean;
}

type State =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "error"; message: string }
  /** The browser blocked the new tab: offer a real link to click instead. */
  | { kind: "blocked"; url: string };

/** A8.3.4.2b — "Open real preview": the draft's ACTUAL website (the same
 * bytes that would be published), in a new tab behind Cloudflare Access.
 * Never rendered inside Studio, never an iframe. The tab is opened
 * synchronously on click (popup-blocker safe), then navigated once the
 * backend returns the URL, or closed if anything fails. */
export function RealPreviewAction({ requestPreview, showNotice = true }: RealPreviewActionProps) {
  const [state, setState] = useState<State>({ kind: "idle" });
  // A ref, not only state: a second click in the same frame must not
  // start a second request before React re-renders the disabled button.
  const inFlight = useRef(false);

  async function handleClick() {
    if (inFlight.current) return;
    inFlight.current = true;
    const tab = openPendingTab();
    setState({ kind: "pending" });
    try {
      const preview = await requestPreview();
      const url = safePreviewUrl(preview.preview_url);
      if (!url) {
        closePendingTab(tab);
        setState({ kind: "error", message: PREVIEW_UNAVAILABLE_MESSAGE });
        return;
      }
      if (!tab || tab.closed) {
        setState({ kind: "blocked", url });
        return;
      }
      try {
        navigatePendingTab(tab, url);
        setState({ kind: "idle" });
      } catch {
        closePendingTab(tab);
        setState({ kind: "blocked", url });
      }
    } catch (caught) {
      closePendingTab(tab);
      setState({ kind: "error", message: previewErrorMessage(caught) });
    } finally {
      inFlight.current = false;
    }
  }

  const pending = state.kind === "pending";

  return (
    <div className="real-preview">
      <button
        type="button"
        className="real-preview__button"
        onClick={handleClick}
        disabled={pending}
        aria-busy={pending}
      >
        {pending ? "Opening preview…" : "Open real preview"}
        <span className="visually-hidden"> (opens in a new tab)</span>
      </button>
      {showNotice && <p className="field-hint real-preview__notice">{REAL_PREVIEW_NOTICE}</p>}
      {state.kind === "error" && (
        <p className="banner banner--error" role="alert">
          {state.message}
        </p>
      )}
      {state.kind === "blocked" && (
        <p className="banner banner--warning" role="status">
          Your browser blocked the new tab.{" "}
          <a href={state.url} target="_blank" rel="noopener noreferrer">
            Open the real preview
            <span className="visually-hidden"> (opens in a new tab)</span>
          </a>
        </p>
      )}
    </div>
  );
}
