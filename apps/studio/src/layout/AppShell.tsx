import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { LoginScreen } from "../features/auth/LoginScreen";
import { NetworkError } from "../lib/api";
import { getCurrentUser, logout, type CurrentUser } from "../lib/auth";

export interface TenantOutletContext {
  tenantId: string;
}

const navLinkClassName = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link nav-link--active" : "nav-link");

type SessionState =
  | { status: "loading" }
  | { status: "logged_out" }
  | { status: "logged_in"; user: CurrentUser; tenantId: string }
  // A real backend/network problem restoring the session — distinct from
  // "logged_out" (no session) so a temporarily-unreachable API doesn't
  // silently present as "please log in" when the real session might
  // still be perfectly valid.
  | { status: "restoration_failed" };

/** A2: the ONLY place Studio decides "is anyone logged in, and as which
 * tenant" — every route renders inside here, and none of them may
 * fall back to their own tenant id source (see TenantOutletContext,
 * consumed via useOutletContext by every route/feature component
 * exactly as before; only WHERE tenantId comes from changed).
 *
 * Session restoration (GET /auth/me) runs once on mount so a page
 * reload doesn't lose a real, still-valid session — the HttpOnly cookie
 * itself already survived the reload; this just re-learns who it
 * belongs to and which tenants it's authorized for. There is
 * deliberately no localStorage fallback of any kind here (the thing A2
 * removed): the authorized tenant list and the selected tenant both
 * live only in this component's state, sourced only from the backend. */
export function AppShell() {
  const [session, setSession] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((user) => {
        if (cancelled) return;
        if (user === null) {
          setSession({ status: "logged_out" });
        } else {
          setSession({ status: "logged_in", user, tenantId: user.tenants[0]?.id ?? "" });
        }
      })
      .catch((cause) => {
        if (cancelled) return;
        if (cause instanceof NetworkError) {
          setSession({ status: "restoration_failed" });
        } else {
          // A non-network, non-401 failure from /auth/me (unexpected) —
          // treat as logged out rather than getting stuck on a
          // perpetual loading screen; the user can simply log in again.
          setSession({ status: "logged_out" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleLoggedIn(user: CurrentUser) {
    setSession({ status: "logged_in", user, tenantId: user.tenants[0]?.id ?? "" });
  }

  function handleTenantIdChange(tenantId: string) {
    setSession((current) => (current.status === "logged_in" ? { ...current, tenantId } : current));
  }

  async function handleLogout() {
    await logout();
    setSession({ status: "logged_out" });
  }

  if (session.status === "loading") {
    return <div className="app-shell__loading">Loading…</div>;
  }

  if (session.status === "restoration_failed") {
    return (
      <div className="app-shell__loading">
        <div className="banner banner--error" role="alert">
          <p className="banner__title">Could not reach the server.</p>
          <p>Check your connection and reload the page.</p>
        </div>
      </div>
    );
  }

  if (session.status === "logged_out") {
    return <LoginScreen onLoggedIn={handleLoggedIn} />;
  }

  const { user, tenantId } = session;

  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <span className="app-shell__title">AI Business Automation Studio</span>
        <nav className="app-shell__nav">
          <NavLink to="/" end className={navLinkClassName}>
            Home
          </NavLink>
          <NavLink to="/businesses/new" className={navLinkClassName}>
            New Business
          </NavLink>
          <NavLink to="/status" className={navLinkClassName}>
            System Status
          </NavLink>
        </nav>
        {/* A2: populated ONLY from GET /auth/me's own tenants list — an
         * operator can switch between tenants they're actually
         * authorized for, never type in an arbitrary id. Selecting one
         * here is just a UI convenience (which authorized tenant this
         * request acts as); the backend's own TenantAccess check is what
         * actually enforces the access itself. */}
        <label className="tenant-field" title="Which of your authorized businesses these actions apply to.">
          Tenant
          {user.tenants.length > 1 ? (
            <select value={tenantId} onChange={(event) => handleTenantIdChange(event.target.value)}>
              {user.tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
          ) : (
            <span className="tenant-field__single">{user.tenants[0]?.name ?? "No authorized tenants"}</span>
          )}
        </label>
        <span className="app-shell__user" title={user.email}>
          {user.email}
        </span>
        <button type="button" className="app-shell__logout" onClick={handleLogout}>
          Log out
        </button>
      </header>
      <main className="app-shell__content">
        <Outlet context={{ tenantId } satisfies TenantOutletContext} />
      </main>
    </div>
  );
}
