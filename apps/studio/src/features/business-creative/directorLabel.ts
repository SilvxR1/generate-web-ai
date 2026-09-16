import type { CreativeDirection } from "../../lib/api";

// Human-readable text for provider_metadata.fallback_reason (a machine
// code shared with the backend's own _HIGGSFIELD_ERROR_MAP/
// FallbackCreativeDirector reasons) — an unrecognized code just omits the
// reason line rather than showing the raw code to a non-technical user.
const FALLBACK_REASON_LABELS: Record<string, string> = {
  higgsfield_model_unavailable: "Higgsfield model unavailable",
  higgsfield_unavailable: "Higgsfield is not configured correctly",
  higgsfield_not_configured: "Higgsfield is not configured on this server",
};

/** Which CreativeDirectorProvider actually produced a candidate —
 * never silently implies Higgsfield when InternalCreativeDirector
 * handled the request (P2.14). Falls back to "internal" only if
 * provider_metadata is somehow missing the field (never happens on a
 * real backend response, but keeps this function total). Appends the
 * operator-safe fallback reason (e.g. "Higgsfield model unavailable")
 * when the backend recorded one, so a fallback never looks identical to
 * an intentional Internal choice. */
export function directorLabel(direction: CreativeDirection): string {
  const provider = direction.provider_metadata?.provider;
  if (provider === "higgsfield") return "Creative Director: Higgsfield";
  const reason = direction.provider_metadata?.fallback_reason;
  const reasonLabel = typeof reason === "string" ? FALLBACK_REASON_LABELS[reason] : undefined;
  return reasonLabel ? `Creative Director: Internal fallback — ${reasonLabel}` : "Creative Director: Internal fallback";
}
