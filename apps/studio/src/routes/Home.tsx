import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { categorizeBusinessFetchError, type CategorizedError } from "../features/business-analysis/errors";
import { BusinessList } from "../features/business-list/BusinessList";
import {
  deactivateAutomation,
  deactivateWebsite,
  deleteBusiness,
  listBusinessSummaries,
  type BusinessSummary,
} from "../lib/api";
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

  // Deletes on the backend first, then — only on success — drops the
  // business from this local list, so the dashboard updates without a
  // full reload. A rejected promise here changes nothing in `state`;
  // BusinessCard (features/business-list) shows the failure itself.
  async function handleDelete(businessId: string) {
    await deleteBusiness(businessId, tenantId);
    setState((prev) =>
      prev.kind === "loaded"
        ? { kind: "loaded", businesses: prev.businesses.filter((business) => business.id !== businessId) }
        : prev,
    );
  }

  // Deactivates on the backend first, then — only on success — patches
  // just this business's website/automation field in the local list
  // (never removed, unlike delete), so the card reflects the new
  // persisted state without a full reload. A rejected promise leaves
  // `state` untouched; BusinessCard shows the failure itself.
  async function handleDeactivateWebsite(businessId: string) {
    const updated = await deactivateWebsite(businessId, tenantId);
    setState((prev) =>
      prev.kind === "loaded"
        ? {
            kind: "loaded",
            businesses: prev.businesses.map((business) =>
              business.id === businessId
                ? { ...business, website: { status: updated.status, live_url: updated.live_url } }
                : business,
            ),
          }
        : prev,
    );
    return updated;
  }

  async function handleDeactivateAutomation(businessId: string) {
    const updated = await deactivateAutomation(businessId, tenantId);
    setState((prev) =>
      prev.kind === "loaded"
        ? {
            kind: "loaded",
            businesses: prev.businesses.map((business) =>
              business.id === businessId
                ? { ...business, automation: { status: updated.status, active: updated.active } }
                : business,
            ),
          }
        : prev,
    );
    return updated;
  }

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
        <BusinessList
          businesses={state.businesses}
          onDelete={handleDelete}
          onDeactivateWebsite={handleDeactivateWebsite}
          onDeactivateAutomation={handleDeactivateAutomation}
        />
      )}

      <p>
        <Link to="/businesses/new">Start a new business →</Link>
      </p>
    </section>
  );
}
