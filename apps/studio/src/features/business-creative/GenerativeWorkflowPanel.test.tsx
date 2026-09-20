import { describe, expect, it } from "vitest";
import type { CreativeDirection } from "../../lib/api";
import { directorLabel } from "./directorLabel";

// P2 continuation (Higgsfield model registry + InternalCreativeDirector
// fallback): proves Studio distinguishes a real Higgsfield-generated
// candidate from an honest Internal fallback, and shows the operator-safe
// reason a fallback happened rather than a raw machine code — never
// silently implying Higgsfield ran when it didn't (P2.14).
function direction(providerMetadata: Record<string, unknown>): CreativeDirection {
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
    provider_metadata: providerMetadata,
    is_recommended: true,
    selection_rationale: null,
    credits_used: null,
    developed_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("directorLabel", () => {
  it("shows Higgsfield for a real Higgsfield-produced candidate", () => {
    expect(directorLabel(direction({ provider: "higgsfield" }))).toBe("Creative Director: Higgsfield");
  });

  it("shows the model-unavailable reason for a Higgsfield model_not_found fallback", () => {
    expect(
      directorLabel(direction({ provider: "internal_fallback", fallback_reason: "higgsfield_model_unavailable" })),
    ).toBe("Creative Director: Internal fallback — Higgsfield model unavailable");
  });

  it("shows the not-configured reason when Higgsfield credentials are missing", () => {
    expect(
      directorLabel(direction({ provider: "internal_fallback", fallback_reason: "higgsfield_not_configured" })),
    ).toBe("Creative Director: Internal fallback — Higgsfield is not configured on this server");
  });

  it("explains when no suitable Higgsfield model could satisfy the request", () => {
    expect(
      directorLabel(direction({ provider: "internal_fallback", fallback_reason: "higgsfield_no_suitable_model" })),
    ).toBe("Creative Director: Internal fallback — No suitable Higgsfield model for this request");
  });

  it("falls back to the plain label for an unrecognized reason code, never a raw machine code", () => {
    const label = directorLabel(direction({ provider: "internal_fallback", fallback_reason: "something_new" }));
    expect(label).toBe("Creative Director: Internal fallback");
    expect(label).not.toContain("something_new");
  });

  it("is total even if provider_metadata is somehow missing the field", () => {
    expect(directorLabel(direction({}))).toBe("Creative Director: Internal fallback");
  });
});
