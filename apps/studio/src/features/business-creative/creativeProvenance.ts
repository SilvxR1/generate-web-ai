import type { AssetPurpose, BrandMode, CreativeDirection, CreativeGenerationLevel } from "../../lib/api";

// P2.2: labels, options and provenance display for generated creative
// directions. Pure functions over the API response — never reads or shows
// a URL, presigned or otherwise, and never a credential: provenance only
// ever carries asset ids, roles, prompt version/hash and validation
// state (see app.domain.creative.provenance on the backend).

export const DEFAULT_PURPOSE: AssetPurpose = "hero";

export const PURPOSE_OPTIONS: { value: AssetPurpose; label: string }[] = [
  { value: "hero", label: "Hero image (top of the page)" },
  { value: "section", label: "Section image" },
  { value: "background", label: "Background" },
  { value: "product", label: "Product image" },
  { value: "editorial", label: "Editorial image" },
  { value: "texture", label: "Texture / pattern" },
];

/** "" means "use the business's own configured setting". */
export const BRAND_MODE_OPTIONS: { value: BrandMode | ""; label: string }[] = [
  { value: "", label: "Business setting (default)" },
  { value: "preserve", label: "Preserve — stay faithful to the brand" },
  { value: "evolve", label: "Evolve — keep brand DNA, fresh interpretation" },
  { value: "new_direction", label: "New direction — brand informs context only" },
];

export const LEVEL_OPTIONS: { value: CreativeGenerationLevel | ""; label: string }[] = [
  { value: "", label: "Business setting (default)" },
  { value: "basic", label: "Basic" },
  { value: "professional", label: "Professional" },
  { value: "premium", label: "Premium" },
  { value: "cinematic", label: "Cinematic" },
];

const BRAND_SOURCE_LABELS: Record<string, string> = {
  official_logo: "Official logo",
  official_logo_palette: "Official logo colors",
  brand_config_colors: "Brand colors",
  brand_config_style: "Brand style",
  brand_config_typography: "Brand typography",
};

// P2.4: what the image depicts (separate from where it is used) and how
// truthful its subject is. Plain-language labels only — never prompt text.
const VISUAL_INTENT_LABELS: Record<string, string> = {
  product_grounded: "Real product",
  subject_editorial: "Editorial",
  abstract_brand: "Abstract (brand)",
  atmospheric: "Atmospheric",
};

const SUBJECT_GROUNDING_LABELS: Record<string, string> = {
  grounded: "Grounded in a real reference",
  conceptual: "Conceptual (not a real product or place)",
  unknown: "Unknown",
};

export interface ProvenanceRow {
  label: string;
  value: string;
}

function labelFor<T extends string>(options: { value: T | ""; label: string }[], value: unknown): string | null {
  if (typeof value !== "string") return null;
  return options.find((option) => option.value === value)?.label.split(" — ")[0] ?? value;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function validationSummary(validation: Record<string, unknown> | null): string | null {
  if (!validation) return null;
  if (validation.status === "passed") return "Passed metadata checks (visual quality not yet checked)";
  const checks = Array.isArray(validation.checks) ? validation.checks : [];
  const failed = checks
    .map(asRecord)
    .filter((check): check is Record<string, unknown> => check !== null && check.passed === false)
    .map((check) => String(check.name).replace(/_/g, " "));
  return failed.length > 0 ? `Failed: ${failed.join(", ")}` : "Failed metadata checks";
}

/** The provenance shown on a preview card. Rows appear only for data the
 * backend actually recorded — an Internal-fallback direction has no
 * generated-asset provenance, so it shows only its provider. */
export function provenanceRows(direction: CreativeDirection): ProvenanceRow[] {
  const rows: ProvenanceRow[] = [];
  const provider = direction.provider_metadata?.provider;
  if (typeof provider === "string") {
    rows.push({ label: "Provider", value: provider === "higgsfield" ? "Higgsfield" : "Internal fallback" });
  }
  const model = direction.provider_metadata?.job_type;
  if (typeof model === "string") rows.push({ label: "Model", value: model });

  const spec = asRecord(direction.generation_metadata?.creative_spec);
  if (!spec) return rows;

  const purpose = labelFor(PURPOSE_OPTIONS, spec.purpose);
  if (purpose) rows.push({ label: "Purpose", value: purpose });
  const brandMode = labelFor(BRAND_MODE_OPTIONS, spec.brand_mode);
  if (brandMode) rows.push({ label: "Brand mode", value: brandMode });
  const level = labelFor(LEVEL_OPTIONS, spec.creative_level);
  if (level) rows.push({ label: "Creative level", value: level });
  const intent = typeof spec.visual_intent === "string" ? VISUAL_INTENT_LABELS[spec.visual_intent] : undefined;
  if (intent) rows.push({ label: "Visual intent", value: intent });
  const grounding = typeof spec.subject_grounding === "string" ? SUBJECT_GROUNDING_LABELS[spec.subject_grounding] : undefined;
  if (grounding) rows.push({ label: "Subject grounding", value: grounding });

  // P2.3: what informed the brand profile is shown separately from what was
  // actually sent to the image model — an official logo is a brand source
  // but is never a generation reference.
  const brandProfile = asRecord(spec.brand_profile);
  if (brandProfile) {
    const sources = Array.isArray(brandProfile.sources)
      ? brandProfile.sources.map((source) => BRAND_SOURCE_LABELS[String(source)]).filter((label) => label)
      : [];
    rows.push({ label: "Brand sources", value: sources.length > 0 ? sources.join(", ") : "None recorded" });
  }

  const references = Array.isArray(spec.references) ? spec.references.map(asRecord).filter((ref) => ref !== null) : [];
  rows.push({
    label: "Generation references",
    value:
      references.length === 0
        ? "None (brand assets inform the prompt as text only)"
        : references.map((ref, index) => `${index + 1}. ${String(ref?.asset_category ?? "asset")} (${String(ref?.usage)})`).join("; "),
  });

  const selection = asRecord(spec.model_selection);
  if (selection && typeof selection.reason === "string") {
    rows.push({
      label: "Model choice",
      value: selection.reason.startsWith("configured_model_satisfies")
        ? "Configured model"
        : "Selected by capability for this request",
    });
  }

  const validation = validationSummary(asRecord(spec.validation));
  if (validation) rows.push({ label: "Validation", value: validation });
  return rows;
}

/** Internal budgeting units are an estimate — never Higgsfield credits and
 * never USD (the first real generation reported 2.0 internally against a
 * balance change of roughly $0.06). Falls back to the legacy
 * `credits_used` field so directions saved before P2.2 still display. */
export function costLabel(direction: CreativeDirection): string | null {
  const meta = direction.generation_metadata ?? {};
  const units = typeof meta.estimated_generation_units === "number" ? meta.estimated_generation_units : direction.credits_used;
  if (units == null) return null;
  return `~${units} estimated generation units (internal estimate — not Higgsfield credits or USD)`;
}
