import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CreativeDirection } from "../../lib/api";
import { VisualQAPanel } from "./VisualQAPanel";

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

describe("VisualQAPanel", () => {
  it("renders nothing for a direction with no generated image", () => {
    const { container } = render(<VisualQAPanel direction={direction(null)} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows NOT PERFORMED, not a pass, when no visual_qa was recorded", () => {
    render(<VisualQAPanel direction={direction({ purpose: "hero" })} />);

    expect(screen.getByText(/Visual QA: NOT PERFORMED/)).toBeInTheDocument();
    expect(screen.queryByText(/PASS/)).not.toBeInTheDocument();
  });

  it("shows per-check statuses and never presents a coverage gap as passing", () => {
    render(
      <VisualQAPanel
        direction={direction({
          purpose: "hero",
          visual_qa: {
            overall_status: "pass",
            approval_eligible: true,
            blocking_reasons: [],
            warnings: [],
            coverage: { performed: ["image_integrity", "aspect_ratio"], not_performed: ["unwanted_text"], not_applicable: [] },
            checks: [
              { name: "image_integrity", status: "pass", kind: "deterministic", severity: "blocking", method: "m", summary: "Decodes cleanly." },
              { name: "aspect_ratio", status: "pass", kind: "deterministic", severity: "blocking", method: "m", summary: "Matches." },
              {
                name: "unwanted_text",
                status: "not_performed",
                kind: "semantic",
                severity: "informational",
                method: "semantic_analyzer_seam",
                summary: "Not checked.",
                reason: "no_semantic_analyzer_configured",
              },
            ],
          },
        })}
      />,
    );

    expect(screen.getByText(/Visual QA: PASS/)).toBeInTheDocument();
    expect(screen.getByText(/2\/3 checks performed/)).toBeInTheDocument();
    expect(screen.getByText(/Image integrity: PASS/)).toBeInTheDocument();
    expect(screen.getByText(/Unwanted text: NOT PERFORMED/)).toBeInTheDocument();
    expect(screen.getByText(/Not covered: Unwanted text/)).toBeInTheDocument();
  });

  it("shows a blocking failure explicitly", () => {
    render(
      <VisualQAPanel
        direction={direction({
          purpose: "hero",
          visual_qa: {
            overall_status: "fail",
            approval_eligible: false,
            blocking_reasons: ["image_integrity: not a valid image"],
            warnings: [],
            coverage: { performed: ["image_integrity"], not_performed: [], not_applicable: [] },
            checks: [
              { name: "image_integrity", status: "fail", kind: "deterministic", severity: "blocking", method: "m", summary: "Not a valid image." },
            ],
          },
        })}
      />,
    );

    expect(screen.getByText(/Visual QA: FAIL/)).toBeInTheDocument();
    expect(screen.getByText(/blocks recommendation and website generation/)).toBeInTheDocument();
  });

  it("renders palette swatches from validated hex values only", () => {
    render(
      <VisualQAPanel
        direction={direction({
          purpose: "hero",
          visual_qa: {
            overall_status: "warning",
            approval_eligible: true,
            blocking_reasons: [],
            warnings: ["brand_palette_adherence: weak"],
            coverage: { performed: ["brand_palette_adherence"], not_performed: [], not_applicable: [] },
            checks: [
              {
                name: "brand_palette_adherence",
                status: "warning",
                kind: "heuristic",
                severity: "warning",
                method: "m",
                summary: "Weak adherence.",
                evidence: {
                  requested_palette: [{ hex: "#EDB08D", present: false }],
                  dominant_detected_colors: [{ hex: "#D1CBBD", share: 0.85 }],
                  present_count: 0,
                  required_count: 2,
                  brand_related_pixel_fraction: 0,
                  neutral_fraction: 0.9,
                },
              },
            ],
          },
        })}
      />,
    );

    const swatches = document.querySelectorAll(".site-preview__swatch");
    expect(swatches).toHaveLength(2);
    expect(swatches[0]).toHaveAttribute("title", "#EDB08D");
    expect(swatches[1]).toHaveAttribute("title", "#D1CBBD");
  });
});
