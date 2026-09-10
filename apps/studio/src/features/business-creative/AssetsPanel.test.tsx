// LR-01 coverage: multi-file selection/upload, per-file failure handling
// that preserves successful uploads, uniform preview semantics (logo
// uses contain, photos use cover — asserted via CSS class, since jsdom
// doesn't compute real layout), selector labels, and file-input reset
// after a successful upload.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { AssetsPanel } from "./AssetsPanel";
import type { BusinessAsset, BusinessAssetUploadResult } from "../../lib/api";

beforeAll(() => {
  // jsdom has no real createObjectURL — AssetsPanel's pending-photo
  // preview thumbnails call it; a stable stub is enough for these tests.
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
});

function photoAsset(overrides: Partial<BusinessAsset> = {}): BusinessAsset {
  return {
    id: "asset-1",
    business_id: "biz-1",
    kind: "image",
    category: "gallery",
    origin: "uploaded",
    storage_url: "https://api.example.com/uploads/biz-1/photo.jpg",
    original_filename: "photo.jpg",
    alt_text: null,
    generation_id: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function logoAsset(overrides: Partial<BusinessAsset> = {}): BusinessAsset {
  return photoAsset({
    id: "asset-logo",
    kind: "logo",
    category: "logo",
    storage_url: "https://api.example.com/uploads/biz-1/logo.png",
    original_filename: "logo.png",
    ...overrides,
  });
}

function file(name: string, type = "image/png"): File {
  return new File(["fake-bytes"], name, { type });
}

describe("AssetsPanel", () => {
  it("separates the brand logo from business photos into distinct sections", () => {
    render(
      <AssetsPanel
        assets={[logoAsset(), photoAsset()]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={vi.fn()}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole("heading", { name: "Brand logo" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Business & product photos" })).toBeInTheDocument();
    const logoCard = document.querySelector(".assets-panel__card--logo");
    const photoCard = document.querySelector(".assets-panel__card--photo");
    expect(logoCard).not.toBeNull();
    expect(photoCard).not.toBeNull();
  });

  it("supports selecting multiple photo files at once and uploads them together", async () => {
    const user = userEvent.setup();
    const onUploadBatch = vi.fn<(files: File[], category: string) => Promise<BusinessAssetUploadResult[]>>(
      async (files) =>
        files.map((f) => ({
          filename: f.name,
          success: true,
          asset: photoAsset({ id: f.name, original_filename: f.name }),
          error: null,
        })),
    );

    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={onUploadBatch}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const files = [file("a.png"), file("b.png"), file("c.png")];
    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement; // photos input
    await user.upload(input, files);

    expect(screen.getByText("3 photo(s) selected, not yet uploaded:")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Upload 3 photo\(s\)/ }));

    await waitFor(() => expect(onUploadBatch).toHaveBeenCalledTimes(1));
    const call = onUploadBatch.mock.calls[0];
    if (!call) throw new Error("expected onUploadBatch to have been called");
    const [sentFiles] = call;
    expect(sentFiles.map((f: File) => f.name)).toEqual(["a.png", "b.png", "c.png"]);
  });

  it("keeps a failed file selected and shows its error, without losing the fact the others succeeded", async () => {
    const user = userEvent.setup();
    const onUploadBatch = vi.fn<(files: File[], category: string) => Promise<BusinessAssetUploadResult[]>>(
      async (files) =>
        files.map((f) =>
          f.name === "bad.png"
            ? { filename: f.name, success: false, asset: null, error: "Unsupported content type" }
            : { filename: f.name, success: true, asset: photoAsset({ id: f.name }), error: null },
        ),
    );

    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={onUploadBatch}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement;
    await user.upload(input, [file("good.png"), file("bad.png")]);
    await user.click(screen.getByRole("button", { name: /Upload 2 photo\(s\)/ }));

    await waitFor(() => expect(screen.getByText(/Unsupported content type/)).toBeInTheDocument());
    // The failed file stays selected for retry; the successful one is cleared.
    expect(screen.getByText("bad.png")).toBeInTheDocument();
    expect(screen.queryByText("good.png")).not.toBeInTheDocument();
  });

  it("resets the logo file input after a successful upload", async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn().mockResolvedValue(logoAsset());

    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={onUpload}
        onUploadBatch={vi.fn()}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const logoInput = document.querySelectorAll('input[type="file"]')[0] as HTMLInputElement;
    await user.upload(logoInput, file("logo.png"));
    expect(logoInput.files?.[0]?.name).toBe("logo.png");

    await user.click(screen.getByRole("button", { name: "Upload logo" }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(logoInput.value).toBe(""));
  });

  it("labels the photo category selector in human-readable terms, not raw enum values", async () => {
    const user = userEvent.setup();
    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={vi.fn()}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement;
    await user.upload(input, file("a.png"));

    expect(screen.getByText("What do these photos show?")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Hero photo (featured on the homepage)" })).toBeInTheDocument();
  });

  it("keeps 'register an asset hosted elsewhere' collapsed and secondary by default", () => {
    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={vi.fn()}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const details = document.querySelector(".assets-panel__advanced") as HTMLDetailsElement;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    expect(screen.getByText("Image description (optional)")).not.toBeVisible();
  });

  it("uses accessible, non-technical wording for the alt-text field", async () => {
    const user = userEvent.setup();
    render(
      <AssetsPanel
        assets={[]}
        isLoading={false}
        error={null}
        onUpload={vi.fn()}
        onUploadBatch={vi.fn()}
        onAdd={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    await user.click(screen.getByText("Advanced: register an asset already hosted elsewhere"));
    expect(screen.getByText("Image description (optional)")).toBeInTheDocument();
    expect(screen.queryByText(/^Alt text$/)).not.toBeInTheDocument();
  });
});
