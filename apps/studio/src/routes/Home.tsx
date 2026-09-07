import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { categorizeBusinessFetchError, type CategorizedError } from "../features/business-analysis/errors";
import { BusinessList } from "../features/business-list/BusinessList";
import { listBusinessSummaries, type BusinessSummary } from "../lib/api";
import type { TenantOutletContext } from "../layout/AppShell";

type ListState =
  | { kind: "loading" }
  | { kind: "loaded"; businesses: BusinessSummary[] }
  | { kind: "error"; error: CategorizedError };

export function Home() {
  const { tenantId } = useOutletContext<TenantOutletContext>();
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    setState({ kind: "loading" });
    listBusinessSummaries(tenantId)
      .then((businesses) => {
        if (!cancelled) setState({ kind: "loaded", businesses });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ kind: "error", error: categorizeBusinessFetchError(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, reloadToken]);

  return (
    <section>
      <h1>AI Business Automation Studio</h1>
      <p>
        Turn a short business briefing into a ready-to-review website and lead-automation workflow — you approve
        every step before anything goes live.
      </p>

      {!tenantId && <p className="banner banner--warning">Set a Tenant ID above to see your businesses.</p>}

      {tenantId && state.kind === "loading" && <p className="field-hint">Loading your businesses…</p>}

      {tenantId && state.kind === "error" && (
        <div className="banner banner--error">
          <p className="banner__title">{state.error.title}</p>
          <p>{state.error.message}</p>
          <button type="button" onClick={() => setReloadToken((n) => n + 1)}>
            Try again
          </button>
        </div>
      )}

      {tenantId && state.kind === "loaded" && state.businesses.length === 0 && (
        <p className="field-hint">No businesses yet for this tenant.</p>
      )}

      {tenantId && state.kind === "loaded" && state.businesses.length > 0 && (
        <BusinessList businesses={state.businesses} />
      )}

      <p>
        <Link to="/businesses/new">Start a new business →</Link>
      </p>
    </section>
  );
}
