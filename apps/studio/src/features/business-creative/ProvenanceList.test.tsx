import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CreativeDirection } from "../../lib/api";
import { provenanceRows } from "./creativeProvenance";
import { ProvenanceList } from "./ProvenanceList";

// P2.6: Studio shows the Brand Intelligence result read-only — palette swatches,
// where the colors came from and how, and whether typography/style are configured.
// It never offers a configuration UI and never turns backend text into CSS.

function direction(brandProfile: Record<string, unknown>): CreativeDirection {
  return {
    id: "d-1",
    business_id: "b-1",
    creative_generation_id: "g-1",
    concept: { name: "Direction", rationale: "...", narrative: "..." },
    visual_language: {},
    experience: {},
    content_strategy: {},
    references: [],
    constraints: {},
    provider_metadata: { provider: "higgsfield", job_type: "higgsfield-ai/soul/standard" },
    generation_metadata: {
      creative_spec: {
        purpose: "hero",
        brand_profile: { sources: ["official_logo", "official_logo_palette"], ...brandProfile },
        references: [],
      },
    },
    is_recommended: true,
    selection_rationale: null,
    credits_used: 2,
    developed_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

const MEASURED = {
  palette_status: "measured",
  palette_source: "asset_extraction",
  palette: ["#F08679", "#C88A4D", "#773A5B"],
  typography: "not_configured",
  typography_hints: [],
  visual_style: null,
};

describe("Brand Intelligence provenance", () => {
  it("shows the measured palette as swatches with its source, analysis and unconfigured typography/style", () => {
    render(<ProvenanceList rows={provenanceRows(direction(MEASURED))} />);

    const swatches = screen.getAllByTestId("brand-palette-swatch");
    expect(swatches.map((swatch) => swatch.getAttribute("title"))).toEqual(["#F08679", "#C88A4D", "#773A5B"]);
    expect(swatches[0]).toHaveStyle({ background: "#F08679" });
    expect(screen.getByText(/Brand palette: #F08679, #C88A4D, #773A5B/)).toBeInTheDocument();
    expect(screen.getByText(/Palette source: Official logo/)).toBeInTheDocument();
    expect(screen.getByText(/Analysis: Measured from authoritative asset/)).toBeInTheDocument();
    expect(screen.getByText(/Typography: Not configured/)).toBeInTheDocument();
    expect(screen.getByText(/Visual style: Not configured/)).toBeInTheDocument();
  });

  it("shows configured typography and visual style exactly as configured, never inferred", () => {
    const rows = provenanceRows(
      direction({
        palette_status: "configured",
        palette_source: "brand_config",
        palette: ["#E8735A"],
        typography: "configured",
        typography_hints: ["display: Fraunces", "body: Inter"],
        visual_style: "handmade warmth",
      }),
    );
    render(<ProvenanceList rows={rows} />);

    expect(screen.getByText(/Analysis: Configured brand colors/)).toBeInTheDocument();
    expect(screen.getByText(/Typography: display: Fraunces, body: Inter/)).toBeInTheDocument();
    expect(screen.getByText(/Visual style: handmade warmth/)).toBeInTheDocument();
  });

  it("says plainly when no palette could be measured, without inventing colors", () => {
    const rows = provenanceRows(direction({ palette_status: "failed", palette: [], typography: "not_configured" }));
    render(<ProvenanceList rows={rows} />);

    expect(screen.queryAllByTestId("brand-palette-swatch")).toHaveLength(0);
    expect(screen.getByText(/Brand palette: None/)).toBeInTheDocument();
    expect(screen.getByText(/Analysis: Could not be measured/)).toBeInTheDocument();
    expect(screen.queryByText(/Palette source/)).not.toBeInTheDocument();
  });

  it("only ever draws swatches for plain #RRGGBB values — backend text never becomes a style", () => {
    const rows = provenanceRows(
      direction({
        palette_status: "configured",
        palette: ["#E8735A", "red; background:url(https://evil.example/x)", "oklch(0.7 0.1 30)", "#zzzzzz"],
      }),
    );
    render(<ProvenanceList rows={rows} />);

    expect(screen.getAllByTestId("brand-palette-swatch")).toHaveLength(1);
    expect(document.querySelector('[style*="evil"]')).toBeNull(); // shown as inert text at most, never as CSS
  });

  it("adds no Brand Intelligence rows for directions saved before P2.6", () => {
    const text = provenanceRows(direction({})).map((row) => row.label);

    expect(text).toContain("Brand sources");
    expect(text).not.toContain("Brand palette");
    expect(text).not.toContain("Analysis");
  });
});
