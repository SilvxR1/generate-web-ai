// R5: the supervised import panel — a supervised workflow (never "AI
// generation"), distinct lifecycle stages, audited review decisions, and
// preview/approve/publish only through the exact-artifact gates.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SourceImport, SourceImportCapability } from "../../lib/api";
import { SupervisedImportPanel, type SourceImportApi } from "./SupervisedImportPanel";

const capability: SourceImportCapability = {
  enabled: true,
  worker_configured: true,
  max_bytes: 100 * 1024 * 1024,
  api_base_url_configured: true,
  site_origin: "https://site-x.pages.dev",
  supervised_only: true,
};

function item(overrides: Partial<SourceImport> = {}): SourceImport {
  return {
    id: "imp-1",
    status: "needs_review",
    stage: "needs_review",
    original_filename: "nexo.zip",
    zip_sha256: "a".repeat(64),
    zip_size: 1000,
    source_family: "higgsfield-tanstack-static",
    adapter: "higgsfield-tanstack-static@1.0.0",
    supportability: "SUPPORTED_WITH_REVIEW",
    plan_sha256: "b".repeat(64),
    created_at: "2026-10-01T00:00:00Z",
    manifest_sha256: "c".repeat(64),
    business_truth_sha256: "d".repeat(64),
    business_truth_current: true,
    site_origin: "https://site-x.pages.dev",
    api_base_url: "https://api.example",
    inspection: {
      findings: [
        { id: "analytics_or_tracking:gtag", code: "analytics_or_tracking", severity: "review", subject: "gtag",
          detail: "tracking code", source: "generic", resolution: null, approval: null, open: true },
        { id: "remote_script:x", code: "remote_script", severity: "blocker", subject: "x",
          detail: "remote script", source: "generic", resolution: null, approval: null, open: true },
      ],
      forms: [{ form_id: "f#0", fields: [{ name: "fullName", role: "name", label: "Your name", required: true }] }],
      build: { toolchain: "bun", sandbox_steps: [{ label: "build", argv: ["bun", "run", "build"] }], expected_pages: ["index.html"] },
      readiness: [{ code: "legal_identity_missing", severity: "launch_blocker", detail: "legal.tax_id is not in BusinessTruth" }],
    },
    open_reviews: ["analytics_or_tracking:gtag"],
    decisions: [],
    job_status: null,
    job_failure: null,
    error: null,
    draft: null,
    ...overrides,
  } as SourceImport;
}

function api(overrides: Partial<SourceImportApi> = {}): SourceImportApi {
  const current = item();
  return {
    capability: vi.fn().mockResolvedValue(capability),
    list: vi.fn().mockResolvedValue([current]),
    get: vi.fn().mockResolvedValue(current),
    diagnostics: vi.fn().mockResolvedValue({}),
    upload: vi.fn().mockResolvedValue(current),
    decide: vi.fn().mockResolvedValue(item({ status: "ready_to_build", stage: "ready_to_build", open_reviews: [] })),
    reinspect: vi.fn().mockResolvedValue(current),
    build: vi.fn().mockResolvedValue(current),
    visualQa: vi.fn().mockResolvedValue({}),
    preview: vi.fn().mockResolvedValue({ preview_url: "https://p.example" }),
    approve: vi.fn().mockResolvedValue({}),
    publish: vi.fn().mockResolvedValue({}),
    ...overrides,
  };
}

async function openImport(client: SourceImportApi) {
  render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
  const list = await screen.findByRole("list", { name: "Imports" });
  fireEvent.click(within(list).getByRole("button"));
  await screen.findByRole("status");
}

describe("SupervisedImportPanel", () => {
  it("presents a supervised import, never AI generation, and is off when the server says so", async () => {
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={api({ capability: vi.fn().mockResolvedValue({ ...capability, enabled: false }) })} />);
    expect(await screen.findByText(/not enabled on this server/)).toBeTruthy();
    expect(screen.queryByText(/Generate with Higgsfield/i)).toBeNull();
  });

  it("explains the supervised workflow and uploads a ZIP", async () => {
    const client = api();
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
    expect(await screen.findByText(/never contacts Higgsfield/)).toBeTruthy();
    const file = new File(["PK"], "nexo.zip", { type: "application/zip" });
    fireEvent.change(screen.getByLabelText("Export ZIP"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Import and inspect" }));
    await waitFor(() => expect(client.upload).toHaveBeenCalledWith("biz", file, "ten"));
  });

  it("separates blockers (never approvable) from review findings and records a rationale", async () => {
    const client = api();
    await openImport(client);
    const blockers = screen.getByRole("region", { name: "Blockers (cannot be approved)" });
    expect(within(blockers).queryByRole("button", { name: "Approve finding" })).toBeNull();
    const review = screen.getByRole("region", { name: "Needs your review" });
    const approve = within(review).getByRole("button", { name: "Approve finding" }) as HTMLButtonElement;
    expect(approve.disabled).toBe(true); // a rationale is required
    fireEvent.change(within(review).getByLabelText("Rationale for analytics_or_tracking:gtag"), {
      target: { value: "Owner removes it before launch." },
    });
    fireEvent.click(approve);
    await waitFor(() =>
      expect(client.decide).toHaveBeenCalledWith(
        "biz",
        "imp-1",
        { finding_id: "analytics_or_tracking:gtag", decision: "approved", rationale: "Owner removes it before launch." },
        "ten",
      ),
    );
  });

  it("shows inspection results without raw JSON and keeps the build disabled until reviewed", async () => {
    await openImport(api());
    expect(screen.getByText(/Your name \(fullName\) → name/)).toBeTruthy();
    expect(screen.getByText(/legal.tax_id is not in BusinessTruth/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Build on the build worker" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Needs review");
  });

  it("does not let an artifact with gate problems be approved, and preview never approves", async () => {
    const ready = item({
      status: "preview_ready",
      stage: "preview_ready",
      open_reviews: [],
      draft: {
        id: "d1", status: "ready", artifact_sha256: "e".repeat(64), approved_artifact_sha256: null, build_error: null,
        preview_url: null, visual_qa_current: false, visual_qa_passed: null,
        gate_problems: ["Visual QA has not been run for this exact artifact (or is stale); run it before approving."],
      },
    });
    const client = api({ list: vi.fn().mockResolvedValue([ready]), get: vi.fn().mockResolvedValue(ready) });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await openImport(client);
    expect(screen.getByRole("status").textContent).toBe("Preview ready — not approved yet");
    expect((screen.getByRole("button", { name: "Approve this artifact" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Publish approved artifact" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Preview (does not approve)" }));
    await waitFor(() => expect(client.preview).toHaveBeenCalledWith("biz", "d1", "ten"));
    expect(client.approve).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it("publishes only an approved artifact", async () => {
    const approved = item({
      status: "preview_ready",
      stage: "approved",
      open_reviews: [],
      draft: {
        id: "d1", status: "approved", artifact_sha256: "e".repeat(64), approved_artifact_sha256: "e".repeat(64),
        build_error: null, preview_url: null, visual_qa_current: true, visual_qa_passed: true, gate_problems: [],
      },
    });
    const client = api({ list: vi.fn().mockResolvedValue([approved]), get: vi.fn().mockResolvedValue(approved) });
    await openImport(client);
    expect(screen.getByRole("status").textContent).toBe("Artifact approved — ready to publish");
    fireEvent.click(screen.getByRole("button", { name: "Publish approved artifact" }));
    await waitFor(() => expect(client.publish).toHaveBeenCalledWith("biz", "d1", "ten"));
  });

  it("shows a safe message, never a stack trace, when an action fails", async () => {
    const client = api({ build: vi.fn().mockRejectedValue(new Error("No build worker is configured on this server.")) });
    const reviewed = item({ status: "ready_to_build", stage: "ready_to_build", open_reviews: [] });
    client.list = vi.fn().mockResolvedValue([reviewed]);
    client.get = vi.fn().mockResolvedValue(reviewed);
    await openImport(client);
    fireEvent.click(screen.getByRole("button", { name: "Build on the build worker" }));
    expect(await screen.findByText("No build worker is configured on this server.")).toBeTruthy();
  });
});
