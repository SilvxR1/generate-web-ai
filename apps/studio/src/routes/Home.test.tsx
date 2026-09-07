import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TenantOutletContext } from "../layout/AppShell";
import { Home } from "./Home";

const TENANT_ID = "11111111-1111-1111-1111-111111111111";

function renderPage(tenantId: string = TENANT_ID) {
  function StubShell() {
    return <Outlet context={{ tenantId } satisfies TenantOutletContext} />;
  }

  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<StubShell />}>
          <Route index element={<Home />} />
          <Route path="businesses/:businessId" element={<p>Reopened business page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function businessSummary(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "biz-reforma-pepe",
    name: "Reforma Pepe",
    slug: "reforma-pepe",
    vertical: "home_renovation",
    status: "active",
    location: { city: "Valencia", region: null, country: "ES", postal_code: null },
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-27T00:00:00Z",
    website: { status: "live", live_url: "https://site-reforma-pepe.workers.dev/" },
    automation: { status: "active", active: true },
    ...overrides,
  };
}

describe("Home dashboard", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("no tenant id: prompts to set one instead of fetching", () => {
    renderPage("");

    expect(screen.getByText("Set a Tenant ID above to see your businesses.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loading state: shows a loading message while the summary request is in flight", () => {
    fetchMock.mockReturnValueOnce(new Promise(() => {})); // never resolves during this test
    renderPage();

    expect(screen.getByText("Loading your businesses…")).toBeInTheDocument();
  });

  it("empty state: shows a friendly message when the tenant has no businesses yet", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    renderPage();

    expect(await screen.findByText("No businesses yet for this tenant.")).toBeInTheDocument();
    expect(screen.getByText("Start a new business →")).toBeInTheDocument();
  });

  it("error state: shows a human error and a Try again button, never raw JSON", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(500, { error: { code: "internal_error", message: "Something went wrong." } }),
    );
    renderPage();

    expect(await screen.findByText("Could not load this business")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("error state: Try again re-fetches and can recover into the loaded list", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(500, { error: { code: "internal_error", message: "Something went wrong." } }),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("button", { name: "Try again" });

    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Reforma Pepe")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("network failure: shows a friendly 'can't reach the server' message", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderPage();

    expect(await screen.findByText("Can't reach the server")).toBeInTheDocument();
  });

  it("business list: renders name, vertical/location, and business/website/automation status", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    renderPage();

    expect(await screen.findByText("Reforma Pepe")).toBeInTheDocument();
    expect(screen.getByText("Home renovation · Valencia, ES")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/business-summaries");
  });

  it("business list: a business with no website/automation state yet shows 'Not published' / 'Not activated'", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, [businessSummary({ website: null, automation: null, location: null })]),
    );
    renderPage();

    expect(await screen.findByText("Reforma Pepe")).toBeInTheDocument();
    expect(screen.getByText("Not published")).toBeInTheDocument();
    expect(screen.getByText("Not activated")).toBeInTheDocument();
    // No location on this one — just the vertical, no trailing " · ...".
    expect(screen.getByText("Home renovation")).toBeInTheDocument();
  });

  it("Open reopens the existing business — navigates to /businesses/{id}, never requiring a manually-copied UUID", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    const user = userEvent.setup();
    renderPage();

    const openLink = await screen.findByRole("link", { name: "Open" });
    expect(openLink).toHaveAttribute("href", "/businesses/biz-reforma-pepe");

    await user.click(openLink);

    expect(await screen.findByText("Reopened business page")).toBeInTheDocument();
  });

  it("switching tenant id re-fetches the list for the new tenant", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    const { rerender } = renderPage();
    await screen.findByText("Reforma Pepe");

    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    function StubShellOtherTenant() {
      return <Outlet context={{ tenantId: "22222222-2222-2222-2222-222222222222" } satisfies TenantOutletContext} />;
    }
    rerender(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<StubShellOtherTenant />}>
            <Route index element={<Home />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.queryByText("Reforma Pepe")).not.toBeInTheDocument());
    expect(await screen.findByText("No businesses yet for this tenant.")).toBeInTheDocument();
  });
});

function noContentResponse(): Response {
  return new Response(null, { status: 204 });
}

describe("Home dashboard delete action", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function loadOneBusiness(user: ReturnType<typeof userEvent.setup>) {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    renderPage();
    await screen.findByText("Reforma Pepe");
    await user.click(screen.getByRole("button", { name: "Delete" }));
  }

  it("clicking Delete shows a confirmation step naming the business, without calling the API yet", async () => {
    const user = userEvent.setup();
    const callsBeforeDelete = 1; // just the initial list load
    await loadOneBusiness(user);

    expect(screen.getByText('Delete "Reforma Pepe"?')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm delete" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(callsBeforeDelete);
  });

  it("the Delete and Confirm delete buttons use distinct destructive styling", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(jsonResponse(200, [businessSummary()]));
    renderPage();
    await screen.findByText("Reforma Pepe");

    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass("button--danger");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByRole("button", { name: "Confirm delete" })).toHaveClass("button--danger");
  });

  it("Cancel dismisses the confirmation without calling the delete API", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText('Delete "Reforma Pepe"?')).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1); // still just the initial list load
  });

  it("Confirm delete calls DELETE /businesses/{id} with the tenant header and removes the card without a full reload", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);
    fetchMock.mockResolvedValueOnce(noContentResponse());

    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => expect(screen.queryByText("Reforma Pepe")).not.toBeInTheDocument());
    expect(await screen.findByText("No businesses yet for this tenant.")).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(2); // initial list load + the delete — never a third re-fetch
    const [deleteUrl, deleteInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(deleteUrl).toContain("/businesses/biz-reforma-pepe");
    expect(deleteInit.method).toBe("DELETE");
    const headers = deleteInit.headers as Record<string, string>;
    expect(headers["X-Tenant-Id"]).toBe(TENANT_ID);
  });

  it("disables Cancel and Confirm delete, and shows Deleting…, while the request is in flight", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);
    let resolveDelete!: (value: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => (resolveDelete = resolve)));

    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    const deletingButton = await screen.findByRole("button", { name: "Deleting…" });
    expect(deletingButton).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    resolveDelete(noContentResponse());
    await waitFor(() => expect(screen.queryByText("Reforma Pepe")).not.toBeInTheDocument());
  });

  it("a failed delete shows a friendly error, offers a retry, and keeps the business in the list", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(502, {
        error: { code: "automation_deactivation_failed", message: "Deactivating this automation failed." },
      }),
    );

    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByText("Can't safely delete — deactivating automation failed")).toBeInTheDocument();
    expect(screen.getByText("Deactivating this automation failed.")).toBeInTheDocument();
    // Never removed — the business is still shown, delete did NOT happen.
    expect(screen.getByText("Reforma Pepe")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("Try again after a failed delete retries the same DELETE call", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);
    fetchMock.mockResolvedValueOnce(
      jsonResponse(502, { error: { code: "automation_deactivation_failed", message: "Deactivating failed." } }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await screen.findByRole("button", { name: "Try again" });

    fetchMock.mockResolvedValueOnce(noContentResponse());
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(screen.queryByText("Reforma Pepe")).not.toBeInTheDocument());
    const deleteCalls = fetchMock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "DELETE");
    expect(deleteCalls).toHaveLength(2);
  });

  it("a network failure while deleting shows the same friendly 'can't reach the server' message", async () => {
    const user = userEvent.setup();
    await loadOneBusiness(user);
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await user.click(screen.getByRole("button", { name: "Confirm delete" }));

    expect(await screen.findByText("Can't reach the server")).toBeInTheDocument();
    expect(screen.getByText("Reforma Pepe")).toBeInTheDocument();
  });
});
