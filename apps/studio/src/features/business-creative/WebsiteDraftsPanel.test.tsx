// A8.3.4.2b: generated proposals offer "Open real preview" (the exact
// built website) only where the backend can serve one — READY/APPROVED —
// and the React SiteConfigPreview is only ever a "Content summary".
import { exampleReformaValenciaConfig } from "@generate-web-ai/business-config-types";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WebsiteDraft } from "../../lib/api";
import { WebsiteDraftsPanel } from "./WebsiteDraftsPanel";

function draft(overrides: Partial<WebsiteDraft> = {}): WebsiteDraft {
  return {
    id: "draft-1",
    business_id: "biz-1",
    creative_generation_id: "gen-1",
    engine: "deterministic",
    site_config: generateSiteConfig(exampleReformaValenciaConfig),
    status: "ready",
    build_error: null,
    validation_issues: null,
    approved_at: null,
    published_at: null,
    published_website_id: null,
    created_at: "2026-01-01T00:00:10Z",
    ...overrides,
  };
}

describe("WebsiteDraftsPanel", () => {
  const onApprove = vi.fn();
  const onPublish = vi.fn();
  const onPreview = vi.fn();

  beforeEach(() => {
    onApprove.mockReset();
    onPublish.mockReset();
    onPreview.mockReset();
    vi.stubGlobal("open", vi.fn(() => null));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function renderPanel(drafts: WebsiteDraft[]) {
    return render(
      <WebsiteDraftsPanel
        drafts={drafts}
        isLoading={false}
        error={null}
        onApprove={onApprove}
        onPreview={onPreview}
        onPublish={onPublish}
      />,
    );
  }

  it.each(["ready", "approved"] as const)("a %s draft offers Open real preview", (status) => {
    renderPanel([draft({ status })]);
    expect(screen.getByRole("button", { name: /Open real preview/ })).toBeInTheDocument();
    expect(screen.getByText(/Your live site won't change until you publish/)).toBeInTheDocument();
  });

  it.each(["published", "build_failed", "building", "draft"] as const)(
    "a %s draft never offers a real-preview action",
    (status) => {
      renderPanel([draft({ status })]);
      expect(screen.queryByRole("button", { name: /real preview/i })).not.toBeInTheDocument();
    },
  );

  it("labels the React summary as Content summary, never as a preview", async () => {
    const user = userEvent.setup();
    renderPanel([draft()]);

    expect(screen.queryByRole("button", { name: /^(Open|Hide) preview$/ })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Content summary" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Hide content summary" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/only accurate in the real preview/)).toBeInTheDocument();
    expect(onPreview).not.toHaveBeenCalled();
  });

  it("Open real preview calls only the preview action — never approve or publish", async () => {
    const user = userEvent.setup();
    onPreview.mockResolvedValue({
      preview_url: "https://1a2b.gwa-draft-previews.pages.dev/",
      created_at: "2026-09-29T00:00:00Z",
      expires_at: "2026-10-06T00:00:00Z",
    });
    renderPanel([draft({ id: "draft-a", status: "ready" }), draft({ id: "draft-b", status: "approved" })]);

    const items = screen.getAllByRole("listitem").filter((li) => li.classList.contains("website-drafts-panel__item"));
    await user.click(within(items[1]!).getByRole("button", { name: /Open real preview/ }));

    await waitFor(() => expect(onPreview).toHaveBeenCalledWith("draft-b"));
    expect(onPreview).toHaveBeenCalledTimes(1);
    expect(onApprove).not.toHaveBeenCalled();
    expect(onPublish).not.toHaveBeenCalled();
    // The approved draft still shows its own explicit Publish action.
    expect(within(items[1]!).getByRole("button", { name: "Publish" })).toBeInTheDocument();
  });
});
