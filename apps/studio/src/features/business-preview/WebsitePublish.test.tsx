// A8.4: the first website goes live only through the WebsiteDraft
// lifecycle — Generate website (one build) -> Open real preview (reused
// RealPreviewAction) -> Use this design -> Publish the approved draft.
// No direct SiteConfig publish exists in this component.
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type WebsiteDraft, type WebsiteState } from "../../lib/api";
import { WebsitePublish } from "./WebsitePublish";

const SITE_CONFIG = generateSiteConfig(exampleReformaValenciaConfig);

function draft(overrides: Partial<WebsiteDraft> = {}): WebsiteDraft {
  return {
    id: "draft-1",
    business_id: "biz-1",
    creative_generation_id: null,
    engine: "deterministic",
    site_config: SITE_CONFIG,
    status: "ready",
    build_error: null,
    validation_issues: null,
    approved_at: null,
    published_at: null,
    published_website_id: null,
    created_at: "2026-09-29T00:00:00Z",
    ...overrides,
  };
}

const LIVE: WebsiteState = {
  status: "live",
  live_url: "https://site-biz-1.pages.dev/",
  deployment_id: "d1",
  deployed_at: "x",
  updated_at: "x",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("WebsitePublish (A8.4 draft lifecycle)", () => {
  const onCreateDraft = vi.fn();
  const onPreview = vi.fn();
  const onApprove = vi.fn();
  const onPublish = vi.fn();

  beforeEach(() => {
    for (const fn of [onCreateDraft, onPreview, onApprove, onPublish]) fn.mockReset();
    vi.stubGlobal("open", vi.fn(() => ({ document: document.implementation.createHTMLDocument(""), opener: null, closed: false, close: vi.fn() })));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function renderPublish(websiteState: WebsiteState | null = null) {
    return render(
      <WebsitePublish
        siteConfig={SITE_CONFIG}
        websiteState={websiteState}
        isLoadingWebsiteState={false}
        customDomain={null}
        onCreateDraft={onCreateDraft}
        onPreview={onPreview}
        onApprove={onApprove}
        onPublish={onPublish}
      />,
    );
  }

  it("Generate website creates a draft from the exact SiteConfig, with a loading state and repeated-click protection", async () => {
    const user = userEvent.setup();
    const pending = deferred<WebsiteDraft>();
    onCreateDraft.mockReturnValue(pending.promise);
    renderPublish();

    await user.click(screen.getByRole("button", { name: "Generate website" }));
    const building = screen.getByRole("button", { name: "Building website…" });
    expect(building).toBeDisabled();
    await user.click(building);
    expect(onCreateDraft).toHaveBeenCalledTimes(1);
    expect(onCreateDraft).toHaveBeenCalledWith(SITE_CONFIG);

    pending.resolve(draft());
    expect(await screen.findByRole("button", { name: /Open real preview/ })).toBeInTheDocument();
    expect(onApprove).not.toHaveBeenCalled();
    expect(onPublish).not.toHaveBeenCalled();
  });

  it("READY: Open real preview never approves or publishes; Publish is unavailable until Use this design", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockResolvedValue(draft());
    onPreview.mockResolvedValue({
      preview_url: "https://1a2b.gwa-draft-previews.pages.dev/",
      created_at: "x",
      expires_at: "y",
    });
    renderPublish();
    await user.click(screen.getByRole("button", { name: "Generate website" }));

    await user.click(await screen.findByRole("button", { name: /Open real preview/ }));
    await waitFor(() => expect(onPreview).toHaveBeenCalledWith("draft-1"));
    expect(onApprove).not.toHaveBeenCalled();
    expect(onPublish).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Publish website" })).not.toBeInTheDocument();
    expect(screen.getByText(/Nothing is live yet/)).toBeInTheDocument();
  });

  it("Use this design approves (with a loading state); APPROVED keeps the real preview and exposes Publish", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockResolvedValue(draft());
    const approving = deferred<WebsiteDraft>();
    onApprove.mockReturnValue(approving.promise);
    renderPublish();
    await user.click(screen.getByRole("button", { name: "Generate website" }));

    await user.click(await screen.findByRole("button", { name: "Use this design" }));
    expect(screen.getByRole("button", { name: "Approving…" })).toBeDisabled();
    approving.resolve(draft({ status: "approved", approved_at: "x" }));

    expect(await screen.findByRole("button", { name: "Publish website" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open real preview/ })).toBeInTheDocument();
    expect(onApprove).toHaveBeenCalledWith("draft-1");
    expect(onPublish).not.toHaveBeenCalled(); // approval never publishes
  });

  it("Publish (after confirmation) promotes the approved draft id and returns to the live view", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockResolvedValue(draft());
    onApprove.mockResolvedValue(draft({ status: "approved", approved_at: "x" }));
    onPublish.mockResolvedValue(LIVE);
    const { rerender } = renderPublish();
    await user.click(screen.getByRole("button", { name: "Generate website" }));
    await user.click(await screen.findByRole("button", { name: "Use this design" }));
    await user.click(await screen.findByRole("button", { name: "Publish website" }));
    expect(onPublish).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm publish" }));

    await waitFor(() => expect(onPublish).toHaveBeenCalledWith("draft-1"));
    rerender(
      <WebsitePublish
        siteConfig={SITE_CONFIG}
        websiteState={LIVE}
        isLoadingWebsiteState={false}
        customDomain={null}
        onCreateDraft={onCreateDraft}
        onPreview={onPreview}
        onApprove={onApprove}
        onPublish={onPublish}
      />,
    );
    expect(await screen.findByText(/Published — this website is live/)).toBeInTheDocument();
    // A live site updates through a new draft too — never a direct republish.
    expect(screen.getByRole("button", { name: "Prepare an update from current content" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish again" })).not.toBeInTheDocument();
  });

  it("a failed draft creation shows a safe message, never the raw backend error", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockRejectedValue(
      new ApiError("Traceback: artifact_key website-drafts/abc in R2 bucket", { code: "internal_error", status: 500 }),
    );
    renderPublish();

    await user.click(screen.getByRole("button", { name: "Generate website" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("We couldn't prepare this website. Please try again. Nothing was published.");
    expect(alert.textContent).not.toMatch(/Traceback|artifact_key|R2/);
    expect(screen.getByRole("button", { name: "Generate website" })).toBeEnabled();
  });

  it("a build-failed draft offers no preview, approval or publish — only a retry", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockResolvedValue(draft({ status: "build_failed", build_error: "PlatformContract violation(s): dead CTA" }));
    renderPublish();

    await user.click(screen.getByRole("button", { name: "Generate website" }));

    expect(await screen.findByText("We couldn't build this website. Nothing was published.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /real preview/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use this design" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Publish website" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate website" })).toBeEnabled();
  });

  it("a publish failure on a missing stored website asks to regenerate, without storage details", async () => {
    const user = userEvent.setup();
    onCreateDraft.mockResolvedValue(draft());
    onApprove.mockResolvedValue(draft({ status: "approved", approved_at: "x" }));
    onPublish.mockRejectedValue(
      new ApiError("stored artifact website-drafts/abc failed sha256", { code: "website_draft_artifact_integrity_failed", status: 409 }),
    );
    renderPublish();
    await user.click(screen.getByRole("button", { name: "Generate website" }));
    await user.click(await screen.findByRole("button", { name: "Use this design" }));
    await user.click(await screen.findByRole("button", { name: "Publish website" }));
    await user.click(screen.getByRole("button", { name: "Confirm publish" }));

    expect(await screen.findByText("This website needs to be generated again")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sha256|website-drafts\//);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
