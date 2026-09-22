import type { CreativeDirection } from "../../lib/api";

// P2.7: read-only view of the Image QA result the backend recorded on a
// generated direction (`generation_metadata.creative_spec.visual_qa`). Pure
// functions over the API response — never reads or shows a URL, and never turns
// "not performed" into anything that looks like a pass.
//
// Not the same as the browser QA of website drafts (`artifact.visual_qa_state`,
// see GenerativeWorkflowPanel — that inspects a built site, this an image).

export type QAStatus = "pass" | "warning" | "fail" | "not_performed" | "not_applicable";

const STATUS_LABELS: Record<QAStatus, string> = {
  pass: "PASS",
  warning: "WARNING",
  fail: "FAIL",
  not_performed: "NOT PERFORMED",
  not_applicable: "NOT APPLICABLE",
};

const CHECK_LABELS: Record<string, string> = {
  image_integrity: "Image integrity",
  aspect_ratio: "Aspect ratio",
  brand_palette_adherence: "Brand palette",
  hero_negative_space: "Negative space",
  unwanted_text: "Unwanted text",
  interface_detection: "Interface detection",
  unwanted_logo: "Unwanted logo",
  logo_distortion: "Logo distortion",
  subject_consistency: "Subject consistency",
  brand_drift: "Brand drift",
  visual_artifacts: "Visual artifacts",
};

const REASON_LABELS: Record<string, string> = {
  no_semantic_analyzer_configured: "No analyzer is configured for this check",
  artifact_unavailable: "The generated image could not be retrieved",
  analysis_limits_exceeded: "The image is larger than the analysis limits",
  image_not_decodable: "The image could not be decoded",
  no_brand_palette_requested: "No brand palette was requested",
  no_aspect_ratio_requirement: "No aspect ratio was requested",
  no_directional_composition_requirement: "The scene has no left/right composition requirement",
  palette_not_measurable: "The palette is not in a measurable notation",
  no_opaque_pixels: "The image has no opaque pixels",
  analyzer_error: "The analyzer failed",
  qa_error: "Visual QA failed unexpectedly",
};

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export interface QACheckView {
  name: string;
  label: string;
  status: QAStatus;
  statusLabel: string;
  heuristic: boolean;
  /** "Brand palette: WARNING (heuristic)" */
  headline: string;
  summary: string;
  details: string[];
  requestedSwatches: string[];
  detectedSwatches: string[];
}

export interface QAView {
  overallStatus: QAStatus;
  overallLabel: string;
  approvalEligible: boolean;
  blockingReasons: string[];
  warnings: string[];
  performedCount: number;
  totalCount: number;
  notPerformedLabels: string[];
  checks: QACheckView[];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asStatus(value: unknown): QAStatus {
  return typeof value === "string" && value in STATUS_LABELS ? (value as QAStatus) : "not_performed";
}

function pct(value: unknown): string {
  return typeof value === "number" ? `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%` : "?";
}

function num(value: unknown, digits = 2): string {
  return typeof value === "number" ? value.toFixed(digits) : "?";
}

function colors(value: unknown[]): string[] {
  return strings(value).filter((color) => HEX_COLOR.test(color));
}

function details(name: string, status: QAStatus, evidence: Record<string, unknown> | null, reason: unknown): string[] {
  if (status === "not_performed" || status === "not_applicable") {
    const text = typeof reason === "string" ? (REASON_LABELS[reason] ?? reason.replace(/_/g, " ")) : null;
    return text ? [text] : [];
  }
  if (!evidence) return [];
  if (name === "image_integrity") {
    const kb = typeof evidence.byte_size === "number" ? `, ${Math.round(evidence.byte_size / 1024)} KB` : "";
    return [
      `${String(evidence.format)} ${String(evidence.width)}×${String(evidence.height)}${kb}`,
    ];
  }
  if (name === "aspect_ratio") {
    return [
      `${String(evidence.actual_width)}×${String(evidence.actual_height)} (${num(evidence.actual_ratio, 3)}) vs ${String(evidence.expected_ratio_text)} — deviation ${pct(evidence.deviation)}, tolerance ${pct(evidence.tolerance)}`,
    ];
  }
  if (name === "brand_palette_adherence") {
    const requested = Array.isArray(evidence.requested_palette) ? evidence.requested_palette.length : 0;
    return [
      `${String(evidence.present_count)} of ${requested} requested colors present (at least ${String(evidence.required_count)} expected)`,
      `Brand-related pixels ${pct(evidence.brand_related_pixel_fraction)} · neutral pixels ${pct(evidence.neutral_fraction)}`,
    ];
  }
  if (name === "hero_negative_space") {
    return [
      `Left activity ${num(evidence.left_region_activity)} vs right ${num(evidence.right_region_activity)} (ratio ${num(evidence.activity_ratio)}). Measures visual activity only — it does not detect a subject.`,
    ];
  }
  return [];
}

function checkView(raw: Record<string, unknown>): QACheckView {
  const name = String(raw.name);
  const status = asStatus(raw.status);
  const evidence = asRecord(raw.evidence);
  const heuristic = raw.kind === "heuristic";
  const label = CHECK_LABELS[name] ?? name.replace(/_/g, " ");
  const requested = Array.isArray(evidence?.requested_palette)
    ? (evidence.requested_palette as unknown[]).map(asRecord)
    : [];
  const detected = Array.isArray(evidence?.dominant_detected_colors)
    ? (evidence.dominant_detected_colors as unknown[]).map(asRecord)
    : [];
  const isNotSkipped = status !== "not_performed" && status !== "not_applicable";
  return {
    name,
    label,
    status,
    statusLabel: STATUS_LABELS[status],
    heuristic,
    headline: `${label}: ${STATUS_LABELS[status]}${heuristic && isNotSkipped ? " (heuristic)" : ""}`,
    summary: typeof raw.summary === "string" ? raw.summary : "",
    details: details(name, status, evidence, raw.reason),
    requestedSwatches: name === "brand_palette_adherence" ? colors(requested.map((entry) => entry?.hex)) : [],
    detectedSwatches: name === "brand_palette_adherence" ? colors(detected.map((entry) => entry?.hex)) : [],
  };
}

/** The Visual QA view of one direction, or null when the direction has no
 * generated image (an internal-fallback direction) — nothing is claimed there. */
export function visualQaView(direction: CreativeDirection): QAView | null {
  const spec = asRecord(direction.generation_metadata?.creative_spec);
  if (!spec || spec.generated_image === false) return null;
  const qa = asRecord(spec.visual_qa);
  if (!qa) {
    return {
      overallStatus: "not_performed",
      overallLabel: STATUS_LABELS.not_performed,
      approvalEligible: true,
      blockingReasons: [],
      warnings: [],
      performedCount: 0,
      totalCount: 0,
      notPerformedLabels: [],
      checks: [],
    };
  }
  const checks = (Array.isArray(qa.checks) ? qa.checks : [])
    .map(asRecord)
    .filter((c): c is Record<string, unknown> => c !== null)
    .map(checkView);
  const coverage = asRecord(qa.coverage);
  const performed = strings(coverage?.performed);
  const notPerformed = strings(coverage?.not_performed);
  const notApplicable = strings(coverage?.not_applicable);
  const overall = asStatus(qa.overall_status);
  return {
    overallStatus: overall,
    overallLabel: STATUS_LABELS[overall],
    approvalEligible: qa.approval_eligible !== false,
    blockingReasons: strings(qa.blocking_reasons),
    warnings: strings(qa.warnings),
    performedCount: performed.length,
    totalCount: performed.length + notPerformed.length + notApplicable.length,
    notPerformedLabels: notPerformed.map((name) => CHECK_LABELS[name] ?? name),
    checks,
  };
}

/** True only when the backend recorded a BLOCKING Visual QA failure. */
export function isBlockedByVisualQa(direction: CreativeDirection): boolean {
  const spec = asRecord(direction.generation_metadata?.creative_spec);
  return asRecord(spec?.visual_qa)?.approval_eligible === false;
}
