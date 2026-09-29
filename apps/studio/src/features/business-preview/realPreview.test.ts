// A8.3.4.2b: the real-preview helpers — URL validation before a tab is
// ever navigated, owner-safe error mapping, and the typed API client
// that keeps only the documented preview fields.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, NetworkError, previewWebsiteDraft } from "../../lib/api";
import {
  PREVIEW_REGENERATE_MESSAGE,
  PREVIEW_UNAVAILABLE_MESSAGE,
  previewErrorMessage,
  safePreviewUrl,
} from "./realPreview";

describe("safePreviewUrl", () => {
  it.each([
    "https://1a2b3c4d.gwa-draft-previews.pages.dev/",
    "https://d-0123456789abcdef01234567.gwa-draft-previews.pages.dev",
    "https://gwa-draft-previews.pages.dev/",
    "https://1A2B.GWA-DRAFT-PREVIEWS.PAGES.DEV/",
  ])("accepts the preview project's HTTPS hosts: %s", (url) => {
    expect(safePreviewUrl(url)).not.toBeNull();
  });

  it.each([
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "blob:https://gwa-draft-previews.pages.dev/1234",
    "file:///etc/passwd",
    "http://1a2b.gwa-draft-previews.pages.dev/",
    "https://gwa-draft-previews.pages.dev.attacker.com/",
    "https://evil-gwa-draft-previews.pages.dev/",
    "https://site-884eb76424494bbea6449d8d937f7a9d.pages.dev/",
    "https://cositasypuntos.com/",
    "https://user:pass@1a2b.gwa-draft-previews.pages.dev/",
    "not a url",
    "",
    null,
    undefined,
    42,
  ])("refuses unsafe or unexpected URLs: %s", (url) => {
    expect(safePreviewUrl(url)).toBeNull();
  });
});

describe("previewErrorMessage", () => {
  const apiError = (code: string, status: number, message = "raw backend detail: website-drafts/abc/sha256 mismatch") =>
    new ApiError(message, { code, status });

  it("asks for regeneration when the proposal has no usable stored website", () => {
    expect(previewErrorMessage(apiError("website_draft_artifact_missing", 409))).toBe(PREVIEW_REGENERATE_MESSAGE);
    expect(previewErrorMessage(apiError("website_draft_artifact_integrity_failed", 409))).toBe(PREVIEW_REGENERATE_MESSAGE);
  });

  it("uses a retryable message for provider/storage/network failures, never the raw backend text", () => {
    for (const error of [
      apiError("website_draft_preview_failed", 502),
      apiError("website_draft_artifact_unavailable", 503),
      apiError("preview_publisher_not_configured", 503),
      apiError("http_error", 500),
      new NetworkError(new TypeError("Failed to fetch")),
      new Error("boom"),
    ]) {
      const message = previewErrorMessage(error);
      expect(message).toBe(PREVIEW_UNAVAILABLE_MESSAGE);
      expect(message).not.toMatch(/sha|r2|artifact|website-drafts\/|cloudflare|deployment/i);
    }
  });

  it("keeps the existing sign-in/permission wording for auth failures", () => {
    expect(previewErrorMessage(apiError("not_authenticated", 401, "Please sign in again."))).toBe("Please sign in again.");
  });
});

describe("previewWebsiteDraft", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the draft's preview endpoint and returns only the documented fields", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          preview_url: "https://1a2b.gwa-draft-previews.pages.dev",
          created_at: "2026-09-29T00:00:00Z",
          expires_at: "2026-10-06T00:00:00Z",
          artifact_key: "website-drafts/secret",
          deployment_id: "dep-1",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const preview = await previewWebsiteDraft("biz-1", "draft-1", "tenant-1");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/businesses\/biz-1\/website-drafts\/draft-1\/preview$/);
    expect(init.method).toBe("POST");
    expect(preview).toEqual({
      preview_url: "https://1a2b.gwa-draft-previews.pages.dev",
      created_at: "2026-09-29T00:00:00Z",
      expires_at: "2026-10-06T00:00:00Z",
    });
  });
});
