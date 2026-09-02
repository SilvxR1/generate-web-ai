import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getStoredTenantId, setStoredTenantId } from "../lib/tenant";

export interface TenantOutletContext {
  tenantId: string;
}

const navLinkClassName = ({ isActive }: { isActive: boolean }) => (isActive ? "nav-link nav-link--active" : "nav-link");

export function AppShell() {
  const [tenantId, setTenantId] = useState(() => getStoredTenantId());

  function handleTenantIdChange(value: string) {
    setTenantId(value);
    setStoredTenantId(value);
  }

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
        <label className="tenant-field" title="Identifies which business account these actions apply to — not a login.">
          Tenant ID
          <input
            type="text"
            value={tenantId}
            onChange={(event) => handleTenantIdChange(event.target.value)}
            placeholder="dev tenant UUID"
            spellCheck={false}
          />
        </label>
      </header>
      <main className="app-shell__content">
        <Outlet context={{ tenantId } satisfies TenantOutletContext} />
      </main>
    </div>
  );
}
