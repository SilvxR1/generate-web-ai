import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useOutletContext } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell, type TenantOutletContext } from "./AppShell";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function TenantProbe() {
  const { tenantId } = useOutletContext<TenantOutletContext>();
  return <p>tenant: {tenantId}</p>;
}

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<TenantProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

const AUTH_RESPONSE = {
  user_id: "user-1",
  email: "owner@acme.studio",
  csrf_token: "csrf-abc",
  tenants: [{ id: "tenant-a", name: "Acme Studio", role: "owner" }],
};

describe("AppShell", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the login screen when there is no existing session", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: "not_authenticated", message: "Not authenticated." } }));

    renderApp();

    expect(await screen.findByText("AI Business Automation Studio")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init).toMatchObject({ credentials: "include" });
  });

  it("restores a real session on mount and renders the authorized tenant", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, AUTH_RESPONSE));

    renderApp();

    expect(await screen.findByText("tenant: tenant-a")).toBeInTheDocument();
    expect(screen.getByText("Acme Studio")).toBeInTheDocument();
    expect(screen.getByTitle("owner@acme.studio")).toHaveTextContent("owner@acme.studio");
  });

  it("logs in successfully and shows the authorized tenant, never a free-text tenant field", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: "not_authenticated", message: "Not authenticated." } }));
    fetchMock.mockResolvedValueOnce(jsonResponse(200, AUTH_RESPONSE));

    renderApp();
    await screen.findByLabelText("Email");

    await userEvent.type(screen.getByLabelText("Email"), "owner@acme.studio");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("tenant: tenant-a")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("dev tenant UUID")).not.toBeInTheDocument();

    const [loginUrl, loginInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(String(loginUrl)).toContain("/auth/login");
    expect(loginInit).toMatchObject({ method: "POST", credentials: "include" });
    expect(JSON.parse(loginInit.body as string)).toEqual({
      email: "owner@acme.studio",
      password: "correct horse battery staple",
    });
  });

  it("shows the backend's error message on a failed login", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: "not_authenticated", message: "Not authenticated." } }));
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: "invalid_credentials", message: "Invalid email or password." } }));

    renderApp();
    await screen.findByLabelText("Email");

    await userEvent.type(screen.getByLabelText("Email"), "owner@acme.studio");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
  });

  it("logs out and returns to the login screen", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, AUTH_RESPONSE));
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    renderApp();
    await screen.findByText("tenant: tenant-a");

    await userEvent.click(screen.getByRole("button", { name: "Log out" }));

    await waitFor(() => expect(screen.getByLabelText("Email")).toBeInTheDocument());
    const [logoutUrl, logoutInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(String(logoutUrl)).toContain("/auth/logout");
    expect(logoutInit).toMatchObject({ method: "POST", credentials: "include" });
  });

  it("shows every authorized tenant in a selector when the user has more than one", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        ...AUTH_RESPONSE,
        tenants: [
          { id: "tenant-a", name: "Acme Studio", role: "owner" },
          { id: "tenant-b", name: "Other Agency", role: "operator" },
        ],
      }),
    );

    renderApp();
    await screen.findByText("tenant: tenant-a");

    const select = screen.getByRole("combobox");
    expect(select).toHaveValue("tenant-a");
    await userEvent.selectOptions(select, "tenant-b");

    expect(await screen.findByText("tenant: tenant-b")).toBeInTheDocument();
  });
});
