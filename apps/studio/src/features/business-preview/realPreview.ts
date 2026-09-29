import { ApiError, NetworkError } from "../../lib/api";

/** A8.3.4.2b — the real preview of a WebsiteDraft is its exact built
 * website, deployed by the backend to the dedicated preview Pages
 * project (apps/api's app.publishing.cloudflare.engine.PREVIEW_PROJECT_NAME)
 * and protected by Cloudflare Access. The backend is authoritative for
 * the URL; this is only a defense-in-depth check before Studio navigates
 * a tab to it: HTTPS, no credentials, and that project's hosts only. */
export const PREVIEW_HOST_ROOT = "gwa-draft-previews.pages.dev";

export function safePreviewUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.username || url.password) return null;
  const host = url.hostname.toLowerCase();
  if (host !== PREVIEW_HOST_ROOT && !host.endsWith(`.${PREVIEW_HOST_ROOT}`)) return null;
  return url.href;
}

export const REAL_PREVIEW_NOTICE =
  "Opens the real generated website in a new tab. Your live site won't change until you publish, and form " +
  "submissions or visits in the preview aren't saved. You may be asked to verify your email first.";

/** The React SiteConfigPreview only summarizes content; the real preview
 * is the only accurate view of the built website. */
export const CONTENT_SUMMARY_HINT =
  "A quick look at the text, services, photos and style. Layout, mobile view, navigation and forms are only " +
  "accurate in the real preview.";

export const PREVIEW_UNAVAILABLE_MESSAGE = "We couldn't open the preview right now. Please try again.";
export const PREVIEW_REGENERATE_MESSAGE = "This proposal needs to be regenerated before it can be previewed.";
const PREVIEW_NOT_PREVIEWABLE_MESSAGE = "This proposal can't be previewed anymore.";

/** Owner-facing message for a failed preview request. Backend messages
 * are never shown verbatim for preview failures (they may name storage
 * or integrity internals); sign-in/permission errors keep the existing
 * session wording. */
export function previewErrorMessage(error: unknown): string {
  if (error instanceof NetworkError) return PREVIEW_UNAVAILABLE_MESSAGE;
  if (error instanceof ApiError) {
    if (error.code === "website_draft_artifact_missing" || error.code === "website_draft_artifact_integrity_failed") {
      return PREVIEW_REGENERATE_MESSAGE;
    }
    if (error.code === "website_draft_not_previewable") return PREVIEW_NOT_PREVIEWABLE_MESSAGE;
    if (error.status === 401 || error.status === 403) return error.message;
  }
  return PREVIEW_UNAVAILABLE_MESSAGE;
}

/** Opened synchronously inside the click handler, so popup blockers see
 * a user-initiated tab; navigated only once the preview URL is known.
 * `window.open` with the "noopener" feature returns null (the tab could
 * then never be navigated), so the opener link is severed by hand
 * instead, before anything else happens in it. Returns null when the
 * browser blocked the popup. */
export function openPendingTab(): Window | null {
  const tab = window.open("about:blank", "_blank");
  if (!tab) return null;
  try {
    tab.opener = null;
    tab.document.title = "Opening preview…";
    const message = tab.document.createElement("p");
    message.textContent = "Opening preview…";
    tab.document.body.append(message);
  } catch {
    // Cosmetic only; navigation below still works.
  }
  return tab;
}

/** Navigates the pending tab from INSIDE it, through a
 * rel="noopener noreferrer" link built with DOM APIs (never HTML
 * strings), so the preview receives no Referer from Studio. */
export function navigatePendingTab(tab: Window, url: string): void {
  const link = tab.document.createElement("a");
  link.href = url;
  link.rel = "noopener noreferrer";
  tab.document.body.append(link);
  link.click();
}

export function closePendingTab(tab: Window | null): void {
  try {
    tab?.close();
  } catch {
    // Already closed by the user.
  }
}
