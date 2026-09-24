import { describe, expect, it } from "vitest";
import { ApiError, NetworkError } from "../../lib/api";
import { categorizePublishError, friendlyErrorMessage } from "./errors";

// hotfix P2/creative-directions-500: proves Studio's shared error-message
// helper correctly distinguishes a real network failure (backend
// genuinely unreachable) from a real HTTP application/provider error
// (backend responded, with a structured error body) — the two were being
// conflated in production only because a backend bug (a bare, un-typed
// exception escaping past app.errors's registered handlers) made a real
// Higgsfield failure LOOK like a network failure to the browser (missing
// CORS headers on that specific response shape). This test locks in the
// frontend half of that fix: once the backend correctly returns an
// ApiError-shaped response (verified separately in
// apps/api/tests/test_generative_pipeline_capability.py and the new
// apps/api/tests/test_higgsfield_error_mapping.py), this is what Studio
// must show for it.
describe("friendlyErrorMessage", () => {
  it("shows the real backend message for a Higgsfield-specific ApiError, never the generic network-failure text", () => {
    const error = new ApiError("Higgsfield does not have enough API credits to generate creative directions right now.", {
      code: "higgsfield_insufficient_credits",
      status: 503,
    });

    expect(friendlyErrorMessage(error, "fallback")).toBe(
      "Higgsfield does not have enough API credits to generate creative directions right now.",
    );
  });

  it("shows the real backend message for a model-unavailable ApiError", () => {
    const error = new ApiError("Higgsfield generation is currently unavailable for this workspace.", {
      code: "higgsfield_model_unavailable",
      status: 503,
    });

    expect(friendlyErrorMessage(error, "fallback")).toBe("Higgsfield generation is currently unavailable for this workspace.");
  });

  it("shows the generic 'backend didn't respond' text ONLY for a genuine NetworkError", () => {
    const error = new NetworkError(new TypeError("Failed to fetch"));

    expect(friendlyErrorMessage(error, "fallback")).toBe(
      "The Studio backend didn't respond. Check that it's running and reachable, then try again.",
    );
  });

  it("never shows the network-failure text for any ApiError, regardless of status code", () => {
    const error = new ApiError("Creative direction generation failed.", {
      code: "creative_direction_error",
      status: 502,
    });

    expect(friendlyErrorMessage(error, "fallback")).not.toContain("didn't respond");
  });
});

// A8.1.2: the direct publish route now refuses a build that fails
// PlatformContract (code "platform_contract_violation") — the raw
// violation list belongs under the banner's technical detail only.
describe("categorizePublishError — platform_contract_violation", () => {
  it("shows a plain message and keeps the raw violation as technical detail", () => {
    const raw = 'PlatformContract violation(s): An anchor targets "#contact", which has no matching id="contact".';
    const categorized = categorizePublishError(
      new ApiError(raw, { code: "platform_contract_violation", status: 422 }),
    );

    expect(categorized.message).toBe("Nothing was published. Your live website has not changed.");
    expect(categorized.title).not.toMatch(/PlatformContract/);
    expect(categorized.technicalDetail).toBe(raw);
  });
});
