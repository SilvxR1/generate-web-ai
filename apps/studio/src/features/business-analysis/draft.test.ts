import { describe, expect, it } from "vitest";
import type { AnalyzeBusinessResponse } from "../../lib/api";
import { buildCreatePayload, buildDraftFromAnalysis, slugify, validateDraft } from "./draft";

describe("slugify", () => {
  it("strips accents and punctuation into a URL-safe slug", () => {
    expect(slugify("Peluquería Núñez & Hijos!")).toBe("peluqueria-nunez-hijos");
  });
});

describe("buildDraftFromAnalysis", () => {
  it("maps a full proposed_config onto the editable draft", () => {
    const analysis: AnalyzeBusinessResponse = {
      proposed_config: {
        schema_version: 1,
        business_profile: {
          name: "Cafe del Mar",
          slug: "cafe-del-mar",
          industry: "restaurant",
          description: "Cafeteria en la playa.",
          location: { city: "Alicante", country: "ES", postal_code: "03001" },
          services: [{ id: "cafe", name: "Cafe", description: "Cafe de especialidad." }],
          contact: { email: "hola@cafedelmar.example" },
        },
        lead_management: { enabled: true, sources: ["whatsapp"] },
        automation: { lead_capture: true, follow_up: { enabled: true, delay: "2d", delay_hours: 48 } },
      },
      missing_information: [],
      questions: [],
    };

    const draft = buildDraftFromAnalysis(analysis, "Somos una cafeteria en la playa.");

    expect(draft.name).toBe("Cafe del Mar");
    expect(draft.slug).toBe("cafe-del-mar");
    expect(draft.slugTouched).toBe(true);
    expect(draft.vertical).toBe("restaurant");
    expect(draft.location.city).toBe("Alicante");
    expect(draft.services).toHaveLength(1);
    expect(draft.services[0]?.name).toBe("Cafe");
    expect(draft.contact.email).toBe("hola@cafedelmar.example");
    expect(draft.leadSources).toEqual(["whatsapp"]);
    expect(draft.automation.leadCapture).toBe(true);
    expect(draft.automation.followUpEnabled).toBe(true);
    expect(draft.automation.followUpDelayHours).toBe(48);
  });

  it("defaults follow-up delay to 24h when the proposal enables follow-up without setting delay_hours", () => {
    const analysis: AnalyzeBusinessResponse = {
      proposed_config: {
        schema_version: 1,
        business_profile: { name: "Cafe del Mar", slug: "cafe-del-mar", industry: "restaurant" },
        automation: { lead_capture: true, follow_up: { enabled: true } },
      },
      missing_information: [],
      questions: [],
    };

    const draft = buildDraftFromAnalysis(analysis, "Somos una cafeteria en la playa.");

    expect(draft.automation.followUpDelayHours).toBe(24);
  });

  it("falls back to blank/empty fields when there is no proposal at all", () => {
    const analysis: AnalyzeBusinessResponse = {
      proposed_config: null,
      missing_information: ["business_profile.name"],
      questions: ["What is the business name?"],
    };

    const draft = buildDraftFromAnalysis(analysis, "Somos un negocio pequeño en la ciudad.");

    expect(draft.name).toBe("");
    expect(draft.slug).toBe("");
    expect(draft.vertical).toBe("other");
    expect(draft.services).toEqual([]);
    expect(draft.leadSources).toEqual([]);
    expect(draft.rawDescription).toBe("Somos un negocio pequeño en la ciudad.");
  });
});

describe("validateDraft", () => {
  function baseDraft() {
    return buildDraftFromAnalysis(
      { proposed_config: null, missing_information: [], questions: [] },
      "Un negocio de ejemplo con suficiente texto.",
    );
  }

  it("requires a name and a valid slug", () => {
    const draft = baseDraft();
    const errors = validateDraft(draft);
    expect(errors).toContain("Business name is required.");
    expect(errors.some((e) => e.includes("Slug"))).toBe(true);
  });

  it("passes once the required fields are filled in", () => {
    const draft = { ...baseDraft(), name: "Cafe del Mar", slug: "cafe-del-mar" };
    expect(validateDraft(draft)).toEqual([]);
  });

  it("flags a half-filled location", () => {
    const draft = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      location: { city: "Alicante", region: "", country: "", postalCode: "" },
    };
    expect(validateDraft(draft).some((e) => e.includes("Location"))).toBe(true);
  });

  it("rejects a follow-up delay outside 1-720 hours, only while follow-up is enabled", () => {
    const enabledTooLow = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: { ...baseDraft().automation, followUpEnabled: true, followUpDelayHours: 0 },
    };
    const enabledTooHigh = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: { ...baseDraft().automation, followUpEnabled: true, followUpDelayHours: 721 },
    };
    // Same out-of-range value, but follow-up is off — not a blocking
    // error, since it won't be sent/used either way.
    const disabledOutOfRange = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: { ...baseDraft().automation, followUpEnabled: false, followUpDelayHours: 0 },
    };

    expect(validateDraft(enabledTooLow).some((e) => e.includes("Follow-up delay"))).toBe(true);
    expect(validateDraft(enabledTooHigh).some((e) => e.includes("Follow-up delay"))).toBe(true);
    expect(validateDraft(disabledOutOfRange).some((e) => e.includes("Follow-up delay"))).toBe(false);
  });

  it("accepts the boundary values 1 and 720 hours when follow-up is enabled", () => {
    const atLowerBound = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: { ...baseDraft().automation, followUpEnabled: true, followUpDelayHours: 1 },
    };
    const atUpperBound = {
      ...baseDraft(),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: { ...baseDraft().automation, followUpEnabled: true, followUpDelayHours: 720 },
    };

    expect(validateDraft(atLowerBound)).toEqual([]);
    expect(validateDraft(atUpperBound)).toEqual([]);
  });
});

describe("buildCreatePayload", () => {
  it("produces a POST /businesses body reflecting the (possibly edited) draft", () => {
    const draft = {
      ...buildDraftFromAnalysis({ proposed_config: null, missing_information: [], questions: [] }, "x".repeat(20)),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      vertical: "restaurant" as const,
      leadSources: ["whatsapp" as const],
      services: [{ key: "k1", name: "Cafe", description: "Cafe de especialidad.", category: "" }],
    };

    const payload = buildCreatePayload(draft);

    expect(payload.name).toBe("Cafe del Mar");
    expect(payload.slug).toBe("cafe-del-mar");
    expect(payload.status).toBe("draft");
    expect(payload.config?.business_profile.industry).toBe("restaurant");
    expect(payload.config?.business_profile.services).toEqual([
      { id: "cafe", name: "Cafe", description: "Cafe de especialidad.", category: undefined },
    ]);
    expect(payload.config?.lead_management?.sources).toEqual(["whatsapp"]);
  });

  it("sends delay_hours when follow-up is enabled", () => {
    const draft = {
      ...buildDraftFromAnalysis({ proposed_config: null, missing_information: [], questions: [] }, "x".repeat(20)),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: {
        leadCapture: true,
        leadNotifications: true,
        customerAcknowledgement: false,
        followUpEnabled: true,
        followUpDelayHours: 72,
      },
    };

    const payload = buildCreatePayload(draft);

    expect(payload.config?.automation?.follow_up).toEqual({ enabled: true, delay_hours: 72 });
  });

  it("omits delay_hours when follow-up is disabled, instead of sending a stale/invalid value", () => {
    const draft = {
      ...buildDraftFromAnalysis({ proposed_config: null, missing_information: [], questions: [] }, "x".repeat(20)),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: {
        leadCapture: true,
        leadNotifications: true,
        customerAcknowledgement: false,
        followUpEnabled: false,
        followUpDelayHours: Number.NaN,
      },
    };

    const payload = buildCreatePayload(draft);

    expect(payload.config?.automation?.follow_up).toEqual({ enabled: false, delay_hours: undefined });
  });

  it("enables the matching communication channel so a checked automation box actually delivers", () => {
    const draft = {
      ...buildDraftFromAnalysis({ proposed_config: null, missing_information: [], questions: [] }, "x".repeat(20)),
      name: "Cafe del Mar",
      slug: "cafe-del-mar",
      automation: {
        leadCapture: true,
        leadNotifications: true,
        customerAcknowledgement: false,
        followUpEnabled: false,
        followUpDelayHours: 24,
      },
    };

    const payload = buildCreatePayload(draft);

    expect(payload.config?.communications?.internal_notifications).toEqual({ email: true });
    expect(payload.config?.communications?.customer_notifications).toEqual({ email: false });
  });
});
