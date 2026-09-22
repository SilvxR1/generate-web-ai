// A2: the real authentication client — replaces src/lib/tenant.ts's
// localStorage-trusted tenant UUID entirely. The session itself lives in
// an HttpOnly cookie this code can never read or set directly (the browser
// manages it via `credentials: "include"`, see sendRequest in api.ts); the
// CSRF token a successful login/`GET /auth/me` hands back in its JSON body
// (never in the cookie) is held in api.ts instead of here (setCsrfToken),
// purely to avoid a circular import between the two modules — api.ts is
// what actually needs to read it on every mutating request, because the
// real production Studio/API topology is cross-site and SameSite alone
// cannot be relied on there (see apps/api's app.auth.cookies).
//
// A full page reload re-derives everything here from a fresh GET
// /auth/me — there is nothing worth persisting across reloads (see
// AppShell's own session-restoration effect).

import { API_URL, ApiError, NetworkError, setCsrfToken } from "./api";

export interface AuthorizedTenant {
  id: string;
  name: string;
  role: "owner" | "operator";
}

export interface CurrentUser {
  user_id: string;
  email: string;
  tenants: AuthorizedTenant[];
}

interface AuthResponseBody {
  user_id: string;
  email: string;
  csrf_token: string;
  tenants: AuthorizedTenant[];
}

async function parseErrorBody(response: Response): Promise<{ code: string; message: string }> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } };
    return {
      code: body.error?.code ?? "http_error",
      message: body.error?.message ?? `Request failed with status ${response.status}.`,
    };
  } catch {
    return { code: "http_error", message: `Request failed with status ${response.status}.` };
  }
}

function toCurrentUser(body: AuthResponseBody): CurrentUser {
  setCsrfToken(body.csrf_token);
  return { user_id: body.user_id, email: body.email, tenants: body.tenants };
}

/** POST /auth/login — the one call in this app that ever sends a
 * password, and the one place `credentials: "include"` matters most (it's
 * how the browser is told to store the Set-Cookie response). Never
 * retried automatically and never logs the password anywhere. */
export async function login(email: string, password: string): Promise<CurrentUser> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/auth/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
  } catch (cause) {
    throw new NetworkError(cause);
  }
  if (!response.ok) {
    const { code, message } = await parseErrorBody(response);
    throw new ApiError(message, { code, status: response.status });
  }
  return toCurrentUser((await response.json()) as AuthResponseBody);
}

/** GET /auth/me — session restoration on every page load (AppShell calls
 * this once on mount) and the ONLY source Studio's tenant selector may
 * ever read its options from. Returns null for "not logged in" (401)
 * rather than throwing, since that is the expected, normal state the
 * very first time anyone opens Studio — a real network failure still
 * throws NetworkError so AppShell can tell the two apart. */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/auth/me`, { method: "GET", credentials: "include" });
  } catch (cause) {
    throw new NetworkError(cause);
  }
  if (response.status === 401) {
    setCsrfToken(null);
    return null;
  }
  if (!response.ok) {
    const { code, message } = await parseErrorBody(response);
    throw new ApiError(message, { code, status: response.status });
  }
  return toCurrentUser((await response.json()) as AuthResponseBody);
}

/** POST /auth/logout — idempotent on the backend (see that route's own
 * docstring), so this never throws for "already logged out"; a network
 * failure still surfaces, since a caller may want to know the request
 * never reached the server. Always clears the local CSRF token,
 * regardless of outcome — an operator clicking "Log out" must see the
 * login screen even if the network call itself failed. */
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    setCsrfToken(null);
  }
}
