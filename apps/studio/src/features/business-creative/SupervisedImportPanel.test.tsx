// R5: the supervised import panel — a supervised workflow (never "AI
// generation"), distinct lifecycle stages, audited review decisions, and
// preview/approve/publish only through the exact-artifact gates.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SourceImport, SourceImportCapability } from "../../lib/api";
import { POLL_INTERVAL_MS, SupervisedImportPanel, type SourceImportApi } from "./SupervisedImportPanel";

const capability: SourceImportCapability = {
  enabled: true,
  access: "global",
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
    discard: vi.fn().mockResolvedValue(current),
    hashFile: vi.fn().mockResolvedValue("a".repeat(64)),
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
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={api({ capability: vi.fn().mockResolvedValue({ ...capability, enabled: false, access: "disabled" }) })} />);
    expect(await screen.findByText(/not enabled on this server/)).toBeTruthy();
    expect(screen.queryByText(/Generate with Higgsfield/i)).toBeNull();
  });

  it("marks scoped canary access for this business, and shows no canary note when globally enabled", async () => {
    const scoped = api({ capability: vi.fn().mockResolvedValue({ ...capability, access: "scoped" }) });
    const { unmount } = render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={scoped} />);
    expect(await screen.findByText(/Canary access: supervised imports are enabled for this business only/)).toBeTruthy();
    unmount();
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={api()} />);
    expect(await screen.findByText(/Supervised import: upload a website ZIP/)).toBeTruthy();
    expect(screen.queryByText(/Canary access/)).toBeNull();
  });

  it("explains the supervised workflow and uploads a ZIP", async () => {
    const client = api();
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
    expect(await screen.findByText(/never contacts Higgsfield/)).toBeTruthy();
    const file = new File(["PK"], "nexo.zip", { type: "application/zip" });
    fireEvent.change(screen.getByLabelText("Export ZIP"), { target: { files: [file] } });
    fireEvent.click(await screen.findByRole("button", { name: "Import this exact file" }));
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

// R5.1.3 — the post-build lifecycle: the runbook closes write access right
// after Build, so the panel must follow the build itself and keep existing
// imports readable (read-only) without the supervised write capability.
describe("SupervisedImportPanel post-build lifecycle (R5.1.3)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  const reviewed = item({ status: "ready_to_build", stage: "ready_to_build", open_reviews: [] });
  const building = item({
    status: "building",
    stage: "building",
    open_reviews: [],
    job_status: "running",
    draft: {
      id: "d1", status: "building", artifact_sha256: null, approved_artifact_sha256: null, build_error: null,
      preview_url: null, visual_qa_current: false, visual_qa_passed: null, gate_problems: [],
    },
  });
  const ready = item({
    status: "preview_ready",
    stage: "preview_ready",
    open_reviews: [],
    job_status: "succeeded",
    draft: {
      id: "d1", status: "ready", artifact_sha256: "e".repeat(64), approved_artifact_sha256: null, build_error: null,
      preview_url: null, visual_qa_current: true, visual_qa_passed: true, gate_problems: [],
    },
  });
  const readOnly: SourceImportCapability = {
    ...capability,
    enabled: false,
    access: "disabled",
    mode: "read_only",
    write_enabled: false,
    read_enabled: true,
  };

  const preview = () => screen.getByRole("button", { name: "Preview (does not approve)" }) as HTMLButtonElement;
  const flush = (ms = 0) => act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

  /** Render with real timers (initial load), then switch to fake timers
   * before opening the import, so the poll loop runs on fake time. */
  async function openWithFakeTimers(client: SourceImportApi) {
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
    const list = await screen.findByRole("list", { name: "Imports" });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.click(within(list).getByRole("button"));
    await flush();
  }

  it("keeps Preview disabled right after Build, then enables it when a poll returns READY", async () => {
    const get = vi.fn().mockResolvedValueOnce(reviewed).mockResolvedValueOnce(building).mockResolvedValue(ready);
    const list = vi.fn().mockResolvedValue([reviewed]);
    const client = api({ list, get, build: vi.fn().mockResolvedValue(building) });
    await openWithFakeTimers(client);
    fireEvent.click(screen.getByRole("button", { name: "Build on the build worker" }));
    await flush();
    expect(screen.getByRole("status").textContent).toBe("Building and validating on the build worker");
    expect(preview().disabled).toBe(true);

    await flush(POLL_INTERVAL_MS); // poll 1: still building
    expect(get).toHaveBeenCalledTimes(2);
    expect(preview().disabled).toBe(true);

    await flush(POLL_INTERVAL_MS); // poll 2: authoritative READY
    expect(get).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toBe("Preview ready — not approved yet");
    expect(preview().disabled).toBe(false);
    expect(list.mock.calls.length).toBeGreaterThanOrEqual(3); // the list is refreshed at the outcome

    await flush(POLL_INTERVAL_MS * 20); // terminal: polling has stopped
    expect(get).toHaveBeenCalledTimes(3);
    expect(client.build).toHaveBeenCalledTimes(1); // polling never mutates anything
    expect(client.reinspect).not.toHaveBeenCalled();
    expect(client.decide).not.toHaveBeenCalled();
  });

  it("stops polling when the panel unmounts and never overlaps requests", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const get = vi.fn().mockImplementation(async () => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await Promise.resolve();
      inFlight -= 1;
      return building;
    });
    const client = api({ list: vi.fn().mockResolvedValue([building]), get });
    await openWithFakeTimers(client);
    await flush(POLL_INTERVAL_MS * 3);
    const calls = get.mock.calls.length;
    expect(calls).toBe(4); // the open + one poll per interval
    expect(maxInFlight).toBe(1);
    screen.getByRole("status"); // still mounted
    cleanup();
    await flush(POLL_INTERVAL_MS * 30);
    expect(get).toHaveBeenCalledTimes(calls);
  });

  it("keeps the last good state through a transient polling failure", async () => {
    const get = vi
      .fn()
      .mockResolvedValueOnce(building) // open
      .mockRejectedValueOnce(new Error("Network down")) // poll 1 (API restarting)
      .mockResolvedValue(ready); // poll 2 after back-off
    const client = api({ list: vi.fn().mockResolvedValue([building]), get });
    await openWithFakeTimers(client);
    await flush(POLL_INTERVAL_MS);
    expect(get).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status").textContent).toBe("Building and validating on the build worker");
    expect(screen.queryByText("Network down")).toBeNull();
    expect(document.querySelector(".banner--error")).toBeNull();

    await flush(POLL_INTERVAL_MS); // backing off: not retried yet
    expect(get).toHaveBeenCalledTimes(2);
    await flush(POLL_INTERVAL_MS);
    expect(get).toHaveBeenCalledTimes(3);
    expect(preview().disabled).toBe(false);
  });

  it("shows a soft notice, not an error, after repeated polling failures", async () => {
    const get = vi.fn().mockResolvedValueOnce(building).mockRejectedValue(new Error("Network down"));
    const client = api({ list: vi.fn().mockResolvedValue([building]), get });
    await openWithFakeTimers(client);
    await flush(POLL_INTERVAL_MS * 20);
    expect(screen.getByText(/still checking the build/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Building and validating on the build worker");
    expect(document.querySelector(".banner--error")).toBeNull();
  });

  it("read-only: existing imports stay visible, mutations are hidden, Preview works", async () => {
    const client = api({
      capability: vi.fn().mockResolvedValue(readOnly),
      list: vi.fn().mockResolvedValue([ready]),
      get: vi.fn().mockResolvedValue(ready),
    });
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    await openImport(client);
    expect(screen.getByRole("note").textContent).toMatch(/Read-only/);
    expect(screen.queryByLabelText("Export ZIP")).toBeNull();
    expect(screen.queryByRole("button", { name: "Import and inspect" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Build on the build worker" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-inspect" })).toBeNull();
    const identity = screen.getByRole("region", { name: "Source identity" });
    expect(within(identity).getByText("nexo.zip")).toBeTruthy();
    expect(within(identity).getByText("a".repeat(12))).toBeTruthy();
    const artifact = screen.getByRole("region", { name: "Artifact" });
    expect(within(artifact).getByText("e".repeat(12))).toBeTruthy();
    expect(within(artifact).getByText("passed (this artifact)")).toBeTruthy();
    expect(preview().disabled).toBe(false);
    fireEvent.click(preview());
    await waitFor(() => expect(client.preview).toHaveBeenCalledWith("biz", "d1", "ten"));
    expect(client.approve).not.toHaveBeenCalled();
    open.mockRestore();
  });

  it("read-only: review decisions cannot be recorded", async () => {
    const client = api({ capability: vi.fn().mockResolvedValue(readOnly) });
    await openImport(client);
    expect(screen.getByRole("region", { name: "Needs your review" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve finding" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("fully disabled with no existing imports keeps the existing disabled message", async () => {
    const client = api({
      capability: vi
        .fn()
        .mockResolvedValue({ ...capability, enabled: false, access: "disabled", mode: "disabled", write_enabled: false, read_enabled: false }),
    });
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
    expect(await screen.findByText(/not enabled on this server/)).toBeTruthy();
    expect(client.list).not.toHaveBeenCalled();
  });
});

// R5.2 — pre-upload confirmation, SHA-256 cross-check, discard, Private Preview notice.
describe("SupervisedImportPanel pre-client hardening (R5.2)", () => {
  const nexoSha = "f3fbc3e76caf53f8df4ae6d6819be7afcd24190af396172cd0ca68de31e0ea8f";
  const lumenSha = "d45ee49f033bcfb495db1f18c7fb87ea2867705a577190b72e1246976fc8231a";
  const ready = item({
    status: "preview_ready",
    stage: "preview_ready",
    open_reviews: [],
    draft: {
      id: "d1", status: "ready", artifact_sha256: "e".repeat(64), approved_artifact_sha256: null, build_error: null,
      preview_url: null, visual_qa_current: true, visual_qa_passed: true, gate_problems: [],
    },
  });

  it("confirms the exact file (name, size, local SHA-256, target business) before uploading anything", async () => {
    const hashFile = vi.fn().mockResolvedValue(nexoSha);
    const client = api({ hashFile, upload: vi.fn().mockResolvedValue(item({ zip_sha256: nexoSha })) });
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" businessName="Nexo Reformas" api={client} />);
    const file = new File(["PK-nexo"], "nexo-reformas-web.zip", { type: "application/zip" });
    fireEvent.change(await screen.findByLabelText("Export ZIP"), { target: { files: [file] } });
    const confirm = screen.getByRole("region", { name: "Confirm the file to import" });
    expect(within(confirm).getByText("nexo-reformas-web.zip")).toBeTruthy();
    expect(within(confirm).getByText(/7 bytes/)).toBeTruthy();
    expect(await within(confirm).findByText(nexoSha)).toBeTruthy();
    expect(within(confirm).getByText("Nexo Reformas")).toBeTruthy();
    expect(hashFile).toHaveBeenCalledWith(file);
    expect(client.upload).not.toHaveBeenCalled(); // nothing leaves the browser before the confirmation
    fireEvent.click(within(confirm).getByRole("button", { name: "Import this exact file" }));
    await waitFor(() => expect(client.upload).toHaveBeenCalledWith("biz", file, "ten"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("changing the selected file invalidates the confirmation", async () => {
    const hashFile = vi.fn().mockImplementation((f: File) => Promise.resolve(f.name === "a.zip" ? lumenSha : nexoSha));
    const client = api({ hashFile, upload: vi.fn().mockResolvedValue(item({ zip_sha256: nexoSha })) });
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" businessName="Nexo Reformas" api={client} />);
    const input = await screen.findByLabelText("Export ZIP");
    const first = new File(["x"], "a.zip", { type: "application/zip" });
    const second = new File(["y"], "b.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [first] } });
    expect(await screen.findByText(lumenSha)).toBeTruthy();
    fireEvent.change(input, { target: { files: [second] } });
    expect(await screen.findByText(nexoSha)).toBeTruthy();
    expect(screen.queryByText(lumenSha)).toBeNull();
    expect(screen.queryByText("a.zip")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Import this exact file" }));
    await waitFor(() => expect(client.upload).toHaveBeenCalledWith("biz", second, "ten"));
    expect(client.upload).toHaveBeenCalledTimes(1);
  });

  it("flags a hard error when the server's SHA-256 differs from the confirmed file", async () => {
    const client = api({
      hashFile: vi.fn().mockResolvedValue(nexoSha),
      upload: vi.fn().mockResolvedValue(item({ id: "imp-x", zip_sha256: lumenSha })),
    });
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" businessName="Nexo Reformas" api={client} />);
    fireEvent.change(await screen.findByLabelText("Export ZIP"), {
      target: { files: [new File(["x"], "nexo-reformas-web.zip")] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Import this exact file" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(lumenSha);
    expect(alert.textContent).toContain(nexoSha);
    expect(alert.textContent).toMatch(/Do not build this import/);
  });

  it("discards an import with a required reason and keeps it only in the audit history", async () => {
    const wrong = item({ id: "imp-w", status: "ready_to_build", stage: "ready_to_build", open_reviews: [] });
    const gone = item({
      id: "imp-w",
      status: "discarded",
      stage: "discarded",
      open_reviews: [],
      events: [
        { kind: "discarded", reason: "Wrong export (Lumen) uploaded under Nexo", previous_status: "ready_to_build",
          actor_email: "owner@example.com", snapshot_sha256: lumenSha, created_at: "2026-10-02T10:00:00Z" },
      ],
    });
    const list = vi.fn().mockResolvedValueOnce([wrong]).mockResolvedValue([gone]);
    const client = api({ list, get: vi.fn().mockResolvedValue(wrong), discard: vi.fn().mockResolvedValue(gone) });
    await openImport(client);
    const section = screen.getByRole("region", { name: "Discard this import" });
    const button = within(section).getByRole("button", { name: "Discard import" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true); // a reason is required
    fireEvent.change(within(section).getByLabelText("Reason for discarding"), {
      target: { value: "Wrong export (Lumen) uploaded under Nexo" },
    });
    fireEvent.click(button);
    await waitFor(() =>
      expect(client.discard).toHaveBeenCalledWith("biz", "imp-w", "Wrong export (Lumen) uploaded under Nexo", "ten"),
    );
    expect((await screen.findByRole("note")).textContent).toMatch(/Discarded on .* by owner@example.com/);
    expect(screen.queryByRole("button", { name: "Build on the build worker" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-inspect" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Discard this import" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Imports" })).toBeNull(); // not in the operational list
    expect(screen.getByRole("list", { name: "Discarded imports" })).toBeTruthy();
  });

  it("a discarded import's artifact offers no preview, approval or publish", async () => {
    const gone = { ...ready, status: "discarded" as const, stage: "discarded" };
    const client = api({ list: vi.fn().mockResolvedValue([gone]), get: vi.fn().mockResolvedValue(gone) });
    render(<SupervisedImportPanel businessId="biz" tenantId="ten" api={client} />);
    const history = await screen.findByRole("list", { name: "Discarded imports" });
    fireEvent.click(within(history).getByRole("button"));
    await screen.findByRole("status");
    expect(screen.queryByRole("button", { name: "Preview (does not approve)" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve this artifact" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Publish approved artifact" })).toBeNull();
  });

  it("explains Private Preview form suppression and shows the privacy-safe preview submission count", async () => {
    const tested = { ...ready, draft: { ...ready.draft!, preview_form_submissions: 2, preview_form_last_at: "2026-10-02T09:52:17Z" } };
    const client = api({ list: vi.fn().mockResolvedValue([tested]), get: vi.fn().mockResolvedValue(tested) });
    await openImport(client);
    expect(
      screen.getByText(/Form submissions in Private Preview reach the API for validation but are not stored, notified, automated/),
    ).toBeTruthy();
    expect(screen.getByText(/Preview form submissions received by the API: 2/)).toBeTruthy();
  });
});

