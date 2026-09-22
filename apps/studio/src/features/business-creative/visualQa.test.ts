import { describe, expect, it } from "vitest";
import type { CreativeDirection } from "../../lib/api";
import { isBlockedByVisualQa, visualQaView } from "./visualQa";

// P2.7: Studio must show NOT_PERFORMED as a coverage gap, never as a pass, and
// must never turn arbitrary backend text into a color swatch.

function direction(spec: Record<string, unknown> | null): CreativeDirection {
  return {
    id: "d-1",
    business_id: "b-1",
    creative_generation_id: "g-1",
    concept: { name: "Direction", rationale: "...", narrative: "..." },
    visual_language: {},
    experience: {},
    content_strategy: {},
    references: spec ? ["https://provider.example.com/out.png"] : [],
    constraints: {},
    provider_metadata: { provider: "higgsfield" },
    generation_metadata: spec === null ? {} : { creative_spec: spec },
    is_recommended: true,
    selection_rationale: null,
    credits_used: 2,
    developed_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

const PASS_QA = {
  version: "p2.7-v1",
  overall_status: "pass",
  approval_eligible: true,
  blocking_reasons: [],
  warnings: [],
  coverage: {
    performed: ["image_integrity", "aspect_ratio", "hero_negative_space"],
    not_performed: [
      "unwanted_text",
      "interface_detection",
      "unwanted_logo",
      "logo_distortion",
      "subject_consistency",
      "brand_drift",
      "visual_artifacts",
    ],
    not_applicable: ["brand_palette_adherence"],
  },
  checks: [
    { name: "image_integrity", status: "pass", kind: "deterministic", severity: "blocking", method: "m", summary: "Decodes cleanly." },
    {
      name: "aspect_ratio",
      status: "pass",
      kind: "deterministic",
      severity: "blocking",
      method: "m",
      summary: "Matches 16:9.",
      evidence: { actual_width: 1696, actual_height: 960, actual_ratio: 1.7667, expected_ratio_text: "16:9", deviation: 0.0062, tolerance: 0.02 },
    },
    {
      name: "brand_palette_adherence",
      status: "not_applicable",
      kind: "heuristic",
      severity: "warning",
      method: "m",
      summary: "No brand palette was requested.",
      reason: "no_brand_palette_requested",
    },
    {
      name: "hero_negative_space",
      status: "pass",
      kind: "heuristic",
      severity: "warning",
      method: "m",
      summary: "Left is calmer.",
      evidence: { left_region_activity: 0.09, right_region_activity: 11.2, activity_ratio: 0.008 },
    },
    ...[
      "unwanted_text",
      "interface_detection",
      "unwanted_logo",
      "logo_distortion",
      "subject_consistency",
      "brand_drift",
      "visual_artifacts",
    ].map((name) => ({
      name,
      status: "not_performed",
      kind: "semantic",
      severity: "informational",
      method: "semantic_analyzer_seam",
      summary: "Not checked: no semantic analyzer is configured, so this is a coverage gap, not a pass.",
      reason: "no_semantic_analyzer_configured",
    })),
  ],
};

function specWithQa(qa: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return { purpose: "hero", ...extra, visual_qa: qa };
}

describe("visualQaView", () => {
  it("is null for a direction with no generated image", () => {
    expect(visualQaView(direction(null))).toBeNull();
    expect(visualQaView(direction({ purpose: "hero", generated_image: false }))).toBeNull();
  });

  it("shows not-performed, never pass, when no visual_qa was recorded at all", () => {
    const view = visualQaView(direction({ purpose: "hero" }));

    expect(view).not.toBeNull();
    expect(view!.overallStatus).toBe("not_performed");
    expect(view!.approvalEligible).toBe(true);
    expect(view!.checks).toEqual([]);
  });

  it("summarizes a full pass result with coverage gaps intact", () => {
    const view = visualQaView(direction(specWithQa(PASS_QA)))!;

    expect(view.overallStatus).toBe("pass");
    expect(view.approvalEligible).toBe(true);
    expect(view.performedCount).toBe(3);
    expect(view.totalCount).toBe(11);
    expect(view.notPerformedLabels).toContain("Unwanted text");
    expect(view.notPerformedLabels).toHaveLength(7);
  });

  it("never labels a not_performed or not_applicable check as heuristic-passed", () => {
    const view = visualQaView(direction(specWithQa(PASS_QA)))!;

    const palette = view.checks.find((c) => c.name === "brand_palette_adherence")!;
    const text = view.checks.find((c) => c.name === "unwanted_text")!;
    expect(palette.headline).toBe("Brand palette: NOT APPLICABLE");
    expect(text.headline).toBe("Unwanted text: NOT PERFORMED");
    expect(palette.headline).not.toContain("heuristic");
  });

  it("labels a real heuristic pass distinctly", () => {
    const view = visualQaView(direction(specWithQa(PASS_QA)))!;

    const negativeSpace = view.checks.find((c) => c.name === "hero_negative_space")!;
    expect(negativeSpace.headline).toBe("Negative space: PASS (heuristic)");
  });

  it("surfaces a blocking failure and its reason", () => {
    const qa = {
      ...PASS_QA,
      overall_status: "fail",
      approval_eligible: false,
      blocking_reasons: ["image_integrity: The generated file is not a valid image."],
      checks: [
        {
          name: "image_integrity",
          status: "fail",
          kind: "deterministic",
          severity: "blocking",
          method: "m",
          summary: "The generated file is not a valid image.",
          reason: "malformed_image",
        },
      ],
    };
    const view = visualQaView(direction(specWithQa(qa)))!;

    expect(view.approvalEligible).toBe(false);
    expect(view.blockingReasons[0]).toContain("image_integrity");
    expect(isBlockedByVisualQa(direction(specWithQa(qa)))).toBe(true);
  });

  it("shows requested and detected palette swatches only for #RRGGBB values", () => {
    const qa = {
      ...PASS_QA,
      checks: PASS_QA.checks.map((check) =>
        check.name === "brand_palette_adherence"
          ? {
              name: "brand_palette_adherence",
              status: "warning",
              kind: "heuristic",
              severity: "warning",
              method: "m",
              summary: "Only 0 of 3 requested brand colors have meaningful presence.",
              evidence: {
                requested_palette: [
                  { hex: "#EDB08D", present: false },
                  { hex: "red; background:url(evil)", present: false },
                ],
                dominant_detected_colors: [{ hex: "#D1CBBD", share: 0.85 }],
                present_count: 0,
                required_count: 2,
                brand_related_pixel_fraction: 0,
                neutral_fraction: 0.9,
              },
            }
          : check,
      ),
    };
    const view = visualQaView(direction(specWithQa(qa)))!;

    const palette = view.checks.find((c) => c.name === "brand_palette_adherence")!;
    expect(palette.requestedSwatches).toEqual(["#EDB08D"]);
    expect(palette.detectedSwatches).toEqual(["#D1CBBD"]);
    expect(palette.status).toBe("warning");
  });

  it("is total for a legacy row that has no scene_plan/visual_qa fields", () => {
    expect(() => visualQaView(direction({}))).not.toThrow();
  });
});
