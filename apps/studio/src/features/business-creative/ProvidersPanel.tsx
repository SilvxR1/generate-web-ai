import type { CreativeProviderAvailability } from "../../lib/api";

const PROVIDER_LABELS: Record<string, string> = { internal: "Internal", higgsfield: "Higgsfield" };

/** Honest provider availability (Phase 13) — backed directly by
 * GET .../creative-providers, itself backed by the same DI checks
 * app.dependencies.get_higgsfield_provider uses on the server. Never a
 * hardcoded "coming soon" — Internal shows Available, Higgsfield shows
 * exactly why it isn't, until it's actually configured. */
export function ProvidersPanel({
  providers,
  isLoading,
  error,
}: {
  providers: CreativeProviderAvailability[] | null;
  isLoading: boolean;
  error: string | null;
}) {
  if (isLoading) {
    return <p className="field-hint">Loading provider availability…</p>;
  }
  if (error) {
    return <p className="banner banner--error">Could not load provider availability: {error}</p>;
  }
  if (!providers || providers.length === 0) {
    return null;
  }

  return (
    <ul className="providers-panel">
      {providers.map((provider) => (
        <li key={provider.provider} className="providers-panel__item">
          <span className={provider.available ? "providers-panel__badge--available" : "providers-panel__badge--unavailable"}>
            {provider.available ? "✓" : "✗"}
          </span>
          <strong>{PROVIDER_LABELS[provider.provider] ?? provider.provider}</strong>
          {provider.available ? (
            <span className="field-hint">Available</span>
          ) : (
            <span className="field-hint">{provider.unavailable_reason ?? "Not configured"}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
