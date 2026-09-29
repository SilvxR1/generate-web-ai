// v0.2 S0: the experimental generative workflow (AI-authored code, built
// on the server) mounts only when the server explicitly reports
// `enabled: true` — hidden while checking, when disabled (the default),
// and when the capability check fails. The backend enforces the same gate.
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GenerativeWorkflowGate } from "./GenerativeWorkflowGate";

function capability(enabled: boolean) {
  const sub = { available: true, unavailable_reason: null };
  return {
    enabled,
    creative_director: sub,
    creative_director_provider: "internal",
    frontend_engineer: sub,
    browser_qa: sub,
    artifact_storage: sub,
    artifact_storage_persistent: true,
    business_asset_storage: sub,
    business_asset_storage_persistent: true,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("GenerativeWorkflowGate", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function renderGate() {
    return render(
      <GenerativeWorkflowGate businessId="biz-1" tenantId="t-1">
        <button type="button">Generate website with AI</button>
      </GenerativeWorkflowGate>,
    );
  }

  it("hides the generative controls when the server reports the feature disabled (the default)", async () => {
    fetchMock.mockResolvedValueOnce(json(200, capability(false)));
    renderGate();

    expect(await screen.findByText(/isn't available on this server/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate website with AI/ })).not.toBeInTheDocument();
  });

  it("stays closed while checking and when the capability check fails", async () => {
    let reject!: (reason: unknown) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((_, rej) => (reject = rej)));
    renderGate();

    expect(screen.queryByRole("button", { name: /Generate website with AI/ })).not.toBeInTheDocument();
    reject(new TypeError("offline"));
    expect(await screen.findByText(/isn't available on this server/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generate website with AI/ })).not.toBeInTheDocument();
  });

  it("treats a missing `enabled` field as disabled", async () => {
    const legacy: Record<string, unknown> = { ...capability(true) };
    delete legacy.enabled;
    fetchMock.mockResolvedValueOnce(json(200, legacy));
    renderGate();

    expect(await screen.findByText(/isn't available on this server/)).toBeInTheDocument();
  });

  it("mounts the workflow only when the server explicitly enables it", async () => {
    fetchMock.mockResolvedValueOnce(json(200, capability(true)));
    renderGate();

    await waitFor(() => expect(screen.getByRole("button", { name: /Generate website with AI/ })).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[0]![0])).toMatch(/\/businesses\/biz-1\/generative-pipeline-capability$/);
  });
});
