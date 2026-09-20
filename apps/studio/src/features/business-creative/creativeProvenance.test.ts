import { describe, expect, it } from "vitest";
import type { CreativeDirection } from "../../lib/api";
import {
  BRAND_MODE_OPTIONS,
  DEFAULT_PURPOSE,
  LEVEL_OPTIONS,
  PURPOSE_OPTIONS,
  costLabel,
  provenanceRows,
} from "./creativeProvenance";

// P2.2: proves Studio shows useful, safe provenance for a generated
// creative direction — purpose/provider/model/references/brand mode/
// validation — never a URL or credential, never implies the internal
// estimate is provider credits or USD, and defaults to safe choices.

function direction(overrides: Partial<CreativeDirection> = {}): CreativeDirection {
  return {
    id: "d-1",
    business_id: "b-1",
    creative_generation_id: "g-1",
    concept: { name: "Direction", rationale: "...", narrative: "..." },
    visual_language: {},
    experience: {},
    content_strategy: {},
    references: ["https://provider.example.com/result.png"],
    constraints: {},
    provider_metadata: { provider: "higgsfield", job_type: "higgsfield-ai/soul/reference", job_id: "job-1" },
    generation_metadata: {
      credits_used: 2,
      estimated_generation_units: 2,
      creative_spec: {
        purpose: "hero",
        brand_mode: "preserve",
        creative_level: "premium",
        references: [{ asset_id: "a-1", usage: "identity", asset_category: "logo", asset_kind: "logo" }],
        validation: { status: "passed", checks: [] },
      },
    },
    is_recommended: true,
    selection_rationale: null,
    credits_used: 2,
    developed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function asText(rows: { label: string; value: string }[]): string {
  return rows.map((row) => `${row.label}: ${row.value}`).join("\n");
}

describe("defaults", () => {
  it("defaults to a hero image and to the business's own brand mode and level", () => {
    expect(DEFAULT_PURPOSE).toBe("hero");
    expect(BRAND_MODE_OPTIONS[0]).toMatchObject({ value: "" });
    expect(LEVEL_OPTIONS[0]).toMatchObject({ value: "" });
  });

  it("offers exactly the purposes the backend supports", () => {
    expect(PURPOSE_OPTIONS.map((option) => option.value).sort()).toEqual(
      ["background", "editorial", "hero", "product", "section", "texture"].sort(),
    );
  });

  it("never offers a way to enable generated text", () => {
    const everyLabel = [...PURPOSE_OPTIONS, ...BRAND_MODE_OPTIONS, ...LEVEL_OPTIONS]
      .map((option) => option.label.toLowerCase())
      .join(" ");
    expect(everyLabel).not.toMatch(/\btext\b/);
  });
});

describe("provenanceRows", () => {
  it("shows purpose, provider, model, brand mode, references and validation state", () => {
    const text = asText(provenanceRows(direction()));

    expect(text).toContain("Provider: Higgsfield");
    expect(text).toContain("Model: higgsfield-ai/soul/reference");
    expect(text).toContain("Purpose: Hero image");
    expect(text).toContain("Brand mode: Preserve");
    expect(text).toContain("Creative level: Premium");
    expect(text).toContain("References used: 1. logo (identity)");
    expect(text).toContain("Validation: Passed metadata checks (visual quality not yet checked)");
  });

  it("never claims visual quality was verified", () => {
    expect(asText(provenanceRows(direction()))).toContain("visual quality not yet checked");
  });

  it("names the failed checks when validation fails", () => {
    const failed = direction({
      generation_metadata: {
        creative_spec: {
          purpose: "hero",
          references: [],
          validation: {
            status: "failed",
            checks: [
              { name: "expected_media_type", passed: false },
              { name: "result_exists", passed: true },
            ],
          },
        },
      },
    });

    const text = asText(provenanceRows(failed));
    expect(text).toContain("Validation: Failed: expected media type");
    expect(text).toContain("References used: None");
  });

  it("never exposes any URL, presigned or provider-hosted", () => {
    const withUrls = direction({
      generation_metadata: {
        creative_spec: {
          purpose: "hero",
          references: [{ asset_id: "a-1", usage: "identity", asset_category: "logo" }],
          validation: { status: "passed", checks: [] },
        },
      },
    });

    const text = asText(provenanceRows(withUrls));
    expect(text).not.toContain("http");
    expect(text).not.toContain("provider.example.com");
    expect(text).not.toContain("job-1");
  });

  it("shows only the provider for an internal fallback with no generated-asset provenance", () => {
    const fallback = direction({
      provider_metadata: { provider: "internal_fallback", fallback_reason: "higgsfield_model_unavailable" },
      generation_metadata: { credits_used: 0 },
      references: [],
    });

    expect(provenanceRows(fallback)).toEqual([{ label: "Provider", value: "Internal fallback" }]);
  });

  it("is total for legacy rows with no generation_metadata at all", () => {
    expect(() => provenanceRows(direction({ generation_metadata: undefined, provider_metadata: {} }))).not.toThrow();
  });
});

describe("costLabel", () => {
  it("labels the number as an internal estimate, never Higgsfield credits or USD", () => {
    const label = costLabel(direction()) ?? "";

    expect(label).toContain("2 estimated generation units");
    expect(label).toContain("not Higgsfield credits or USD");
    expect(label).not.toMatch(/\$\s?\d/);
  });

  it("falls back to the legacy credits_used field for rows saved before P2.2", () => {
    const label = costLabel(direction({ generation_metadata: {}, credits_used: 4.5 })) ?? "";
    expect(label).toContain("4.5 estimated generation units");
  });

  it("shows nothing when no estimate exists", () => {
    expect(costLabel(direction({ generation_metadata: undefined, credits_used: null }))).toBeNull();
  });
});
