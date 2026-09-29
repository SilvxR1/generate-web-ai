// A8.3.4.2b: "Open real preview" — a popup-safe new tab (opened
// synchronously on click, navigated after the request resolves, closed on
// failure), no opener/referrer, loading and repeated-click protection, and
// owner-safe errors.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type WebsiteDraftPreview } from "../../lib/api";
import { RealPreviewAction } from "./RealPreviewAction";
import { PREVIEW_REGENERATE_MESSAGE, PREVIEW_UNAVAILABLE_MESSAGE } from "./realPreview";

const PREVIEW_URL = "https://1a2b3c4d.gwa-draft-previews.pages.dev/";

function preview(url = PREVIEW_URL): WebsiteDraftPreview {
  return { preview_url: url, created_at: "2026-09-29T00:00:00Z", expires_at: "2026-10-06T00:00:00Z" };
}

interface FakeTab {
  document: Document;
  opener: unknown;
  closed: boolean;
  close: ReturnType<typeof vi.fn>;
}

function fakeTab(): FakeTab {
  const tab: FakeTab = {
    document: document.implementation.createHTMLDocument(""),
    opener: window,
    closed: false,
    close: vi.fn(() => {
      tab.closed = true;
    }),
  };
  return tab;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("RealPreviewAction", () => {
  let openSpy: ReturnType<typeof vi.fn>;
  let clicked: HTMLAnchorElement[];

  beforeEach(() => {
    openSpy = vi.fn();
    vi.stubGlobal("open", openSpy);
    clicked = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this);
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("is a real button that announces it opens a new tab, with the owner notice", () => {
    render(<RealPreviewAction requestPreview={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Open real preview (opens in a new tab)" });
    expect(button.tagName).toBe("BUTTON");
    expect(screen.getByText(/Your live site won't change until you publish/)).toBeInTheDocument();
    expect(screen.getByText(/aren't saved/)).toBeInTheDocument();
    expect(screen.getByText(/verify your email/)).toBeInTheDocument();
  });

  it("opens a blank tab synchronously on click, before the request resolves (popup-blocker safe)", async () => {
    const user = userEvent.setup();
    const tab = fakeTab();
    openSpy.mockReturnValue(tab);
    const pending = deferred<WebsiteDraftPreview>();
    const requestPreview = vi.fn(() => pending.promise);
    render(<RealPreviewAction requestPreview={requestPreview} />);

    await user.click(screen.getByRole("button", { name: /Open real preview/ }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledWith("about:blank", "_blank");
    expect(requestPreview).toHaveBeenCalledTimes(1);
    expect(tab.opener).toBeNull(); // opener severed immediately
    expect(clicked).toHaveLength(0); // not navigated yet

    pending.resolve(preview());
    await waitFor(() => expect(clicked).toHaveLength(1));
  });

  it("navigates that tab to the returned URL through a noopener/noreferrer link, never an iframe", async () => {
    const user = userEvent.setup();
    const tab = fakeTab();
    openSpy.mockReturnValue(tab);
    render(<RealPreviewAction requestPreview={vi.fn().mockResolvedValue(preview())} />);

    await user.click(screen.getByRole("button", { name: /Open real preview/ }));

    await waitFor(() => expect(clicked).toHaveLength(1));
    const link = clicked[0]!;
    expect(link.ownerDocument).toBe(tab.document); // navigated from inside the new tab
    expect(link.href).toBe(PREVIEW_URL);
    expect(link.rel.split(" ")).toEqual(expect.arrayContaining(["noopener", "noreferrer"]));
    expect(tab.close).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.getByRole("button", { name: /Open real preview/ })).toBeEnabled();
  });

  it("shows a loading state and ignores repeated clicks while the request is pending", async () => {
    const user = userEvent.setup();
    openSpy.mockImplementation(() => fakeTab());
    const pending = deferred<WebsiteDraftPreview>();
    const requestPreview = vi.fn(() => pending.promise);
    render(<RealPreviewAction requestPreview={requestPreview} />);

    const button = screen.getByRole("button", { name: /Open real preview/ });
    await user.click(button);

    const loading = screen.getByRole("button", { name: /Opening preview/ });
    expect(loading).toBeDisabled();
    expect(loading).toHaveAttribute("aria-busy", "true");
    await user.click(loading);
    await user.dblClick(loading);
    expect(requestPreview).toHaveBeenCalledTimes(1);
    expect(openSpy).toHaveBeenCalledTimes(1);

    pending.resolve(preview());
    await waitFor(() => expect(screen.getByRole("button", { name: /Open real preview/ })).toBeEnabled());
  });

  it("closes the temporary tab and shows a safe message when the request fails", async () => {
    const user = userEvent.setup();
    const tab = fakeTab();
    openSpy.mockReturnValue(tab);
    const failure = new ApiError("Artifact website-drafts/abc sha256 mismatch in R2", {
      code: "website_draft_preview_failed",
      status: 502,
    });
    render(<RealPreviewAction requestPreview={vi.fn().mockRejectedValue(failure)} />);

    await user.click(screen.getByRole("button", { name: /Open real preview/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(PREVIEW_UNAVAILABLE_MESSAGE);
    expect(alert.textContent).not.toMatch(/sha256|R2|website-drafts/);
    expect(tab.close).toHaveBeenCalledTimes(1);
    expect(clicked).toHaveLength(0);
  });

  it("asks for regeneration for a legacy proposal without a stored website", async () => {
    const user = userEvent.setup();
    const tab = fakeTab();
    openSpy.mockReturnValue(tab);
    const legacy = new ApiError("legacy", { code: "website_draft_artifact_missing", status: 409 });
    render(<RealPreviewAction requestPreview={vi.fn().mockRejectedValue(legacy)} />);

    await user.click(screen.getByRole("button", { name: /Open real preview/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(PREVIEW_REGENERATE_MESSAGE);
    expect(tab.close).toHaveBeenCalledTimes(1);
  });

  it.each(["javascript:alert(1)", "http://1a2b.gwa-draft-previews.pages.dev/", "https://evil.example.com/"])(
    "refuses an unsafe or unexpected preview URL (%s) and closes the tab",
    async (url) => {
      const user = userEvent.setup();
      const tab = fakeTab();
      openSpy.mockReturnValue(tab);
      render(<RealPreviewAction requestPreview={vi.fn().mockResolvedValue(preview(url))} />);

      await user.click(screen.getByRole("button", { name: /Open real preview/ }));

      expect(await screen.findByRole("alert")).toHaveTextContent(PREVIEW_UNAVAILABLE_MESSAGE);
      expect(tab.close).toHaveBeenCalledTimes(1);
      expect(clicked).toHaveLength(0);
      expect(document.querySelector(`a[href="${url}"]`)).toBeNull();
    },
  );

  it("when the browser blocks the tab, offers a real new-tab link instead", async () => {
    const user = userEvent.setup();
    openSpy.mockReturnValue(null);
    render(<RealPreviewAction requestPreview={vi.fn().mockResolvedValue(preview())} />);

    await user.click(screen.getByRole("button", { name: /Open real preview/ }));

    const link = await screen.findByRole("link", { name: /Open the real preview/ });
    expect(link).toHaveAttribute("href", PREVIEW_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")?.split(" ")).toEqual(expect.arrayContaining(["noopener", "noreferrer"]));
  });
});
