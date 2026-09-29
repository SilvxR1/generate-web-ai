import { useEffect, useState, type ReactNode } from "react";
import { getGenerativePipelineCapability } from "../../lib/api";

interface GenerativeWorkflowGateProps {
  businessId: string;
  tenantId: string;
  children: ReactNode;
}

type GateState = "checking" | "enabled" | "disabled";

/** v0.2 S0 — the experimental generative workflow builds and runs
 * AI-authored code, which the server only allows when
 * `generative_website_builds_enabled` is on (OFF by default; off in
 * production until generation runs in an isolated worker). Fails closed:
 * the workflow mounts only when the server explicitly reports `enabled`,
 * never while checking or when the check fails. The backend enforces the
 * same gate on every generative build route, so this is not the only
 * control. */
export function GenerativeWorkflowGate({ businessId, tenantId, children }: GenerativeWorkflowGateProps) {
  const [state, setState] = useState<GateState>("checking");

  useEffect(() => {
    let cancelled = false;
    getGenerativePipelineCapability(businessId, tenantId)
      .then((capability) => !cancelled && setState(capability.enabled === true ? "enabled" : "disabled"))
      .catch(() => !cancelled && setState("disabled"));
    return () => {
      cancelled = true;
    };
  }, [businessId, tenantId]);

  if (state === "enabled") return <>{children}</>;
  if (state === "checking") return null;
  return <p className="field-hint">Experimental AI website generation isn't available on this server.</p>;
}
