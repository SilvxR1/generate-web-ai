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
