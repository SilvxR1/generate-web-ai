import { useState } from "react";
import { friendlyErrorMessage } from "../business-analysis/errors";
import type { CustomDomainState, WebsiteState } from "../../lib/api";

interface CustomDomainPanelProps {
  websiteState: WebsiteState | null;
  customDomain: CustomDomainState | null;
  isLoading: boolean;
  onAttach: (domain: string) => Promise<CustomDomainState>;
  onRefresh: () => Promise<CustomDomainState>;
  onDetach: () => Promise<CustomDomainState>;
}

type UiState =
  | { kind: "idle" }
  | { kind: "attaching" }
  | { kind: "refreshing" }
  | { kind: "detaching" }
  | { kind: "error"; message: string };

/** Attach/check/detach a business's own domain against its live website.
 * Deliberately blunt about the one thing this app will never do: buy or
 * register a domain on a business's behalf (P0's "DO NOT purchase
 * domains automatically" constraint) — that copy is not conditional on
 * any state below. */
export function CustomDomainPanel({
  websiteState,
  customDomain,
  isLoading,
  onAttach,
  onRefresh,
  onDetach,
}: CustomDomainPanelProps) {
  const [ui, setUi] = useState<UiState>({ kind: "idle" });
  const [domainInput, setDomainInput] = useState("");

  if (isLoading) {
    return <p>Loading domain status…</p>;
  }

  const isWebsiteLive = websiteState?.status === "live";

  async function handleAttach(event: React.FormEvent) {
    event.preventDefault();
    setUi({ kind: "attaching" });
    try {
      await onAttach(domainInput.trim());
      setUi({ kind: "idle" });
      setDomainInput("");
    } catch (caught) {
      setUi({ kind: "error", message: friendlyErrorMessage(caught, "Could not attach this domain.") });
    }
  }

  async function handleRefresh() {
    setUi({ kind: "refreshing" });
    try {
      await onRefresh();
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "error", message: friendlyErrorMessage(caught, "Could not check this domain's status.") });
    }
  }

  async function handleDetach() {
    setUi({ kind: "detaching" });
    try {
      await onDetach();
      setUi({ kind: "idle" });
    } catch (caught) {
      setUi({ kind: "error", message: friendlyErrorMessage(caught, "Could not remove this domain.") });
    }
  }

  return (
    <div className="custom-domain-panel">
      <p className="field-hint">
        Connect a domain this business already owns. generate-web-ai does not purchase, register, or renew domains —
        you must own the domain and be able to edit its DNS records yourself before attaching it here.
      </p>

      {ui.kind === "error" && <p className="banner banner--error">{ui.message}</p>}

      {!isWebsiteLive && (
        <p className="field-hint">Publish this business's website before attaching a custom domain.</p>
      )}

      {isWebsiteLive && !customDomain && (
        <>
          <p className="field-hint">
            If this business doesn't have a domain yet, that's fine — it's fine to configure later, and the site
            stays reachable at its technical preview URL until then.
          </p>
          <form className="custom-domain-panel__attach-form" onSubmit={handleAttach}>
            <label>
              Domain (leave this for later if the business doesn't already own one)
              <input
                type="text"
                value={domainInput}
                onChange={(event) => setDomainInput(event.target.value)}
                placeholder="example.com"
                disabled={ui.kind === "attaching"}
                required
              />
            </label>
            <button type="submit" disabled={ui.kind === "attaching" || domainInput.trim() === ""}>
              {ui.kind === "attaching" ? "Attaching…" : "Attach domain"}
            </button>
          </form>
        </>
      )}

      {customDomain && customDomain.status === "active" && (
        <>
          <p className="banner banner--ok">
            <a href={`https://${customDomain.domain}`} target="_blank" rel="noreferrer noopener">
              {customDomain.domain}
            </a>{" "}
            is active and pointed at this business's website.
          </p>
          <button type="button" onClick={handleDetach} disabled={ui.kind === "detaching"}>
            {ui.kind === "detaching" ? "Removing…" : "Remove domain"}
          </button>
        </>
      )}

      {customDomain && customDomain.status !== "active" && customDomain.status !== "removed" && (
        <div className="custom-domain-panel__pending">
          <p>
            <strong>{customDomain.domain}</strong> is not active yet
            {customDomain.provider_status ? ` (provider status: ${customDomain.provider_status})` : ""}.
          </p>
          {customDomain.cname_target && (
            <p className="field-hint">
              At your DNS provider, add a CNAME record for <code>{customDomain.domain}</code> pointing to{" "}
              <code>{customDomain.cname_target}</code>. This can take a few minutes to verify after you add it.
            </p>
          )}
          {customDomain.error_message && <p className="banner banner--error">{customDomain.error_message}</p>}
          <div className="proposal-actions">
            <button type="button" onClick={handleRefresh} disabled={ui.kind === "refreshing"}>
              {ui.kind === "refreshing" ? "Checking…" : "Check status"}
            </button>
            <button type="button" onClick={handleDetach} disabled={ui.kind === "detaching"}>
              {ui.kind === "detaching" ? "Removing…" : "Remove domain"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
