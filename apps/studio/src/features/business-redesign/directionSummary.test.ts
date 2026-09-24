import { describe, expect, it } from "vitest";
import type { WebsiteCreativeDirection } from "@generate-web-ai/site-config";
import { MODE_LABELS, proposalMode, summarizeDirection } from "./directionSummary";

const base: WebsiteCreativeDirection = {
  version: "1",
  strategy: "evolve",
  family: "artisan",
  palette: { mode: "brand_derived", derivation: "tonal_shift" },
  typography: { pairing: "humanist_serif_display" },
  radius: "round",
  density: "airy",
  sectionOrder: ["gallery", "services", "about"],
  hero: { layout: "split" },
  gallery: { maxItems: 9, layout: "featured_grid" },
  surfaces: { mode: "alternate" },
  cta: { variant: "default" },
  rationale: "Keeps the recognizable identity.",
};

describe("directionSummary", () => {
  it("labels the proposal from the stored strategy", () => {
    expect(MODE_LABELS[proposalMode(base)]).toBe("Refresh");
    expect(MODE_LABELS[proposalMode({ ...base, strategy: "new_direction" })]).toBe("New direction");
    expect(MODE_LABELS[proposalMode({ ...base, strategy: "preserve", palette: { mode: "brand" } })]).toBe("Keep current design");
  });

  it("returns exactly four plain-language items and never the rationale or raw enums", () => {
    const items = summarizeDirection(base);
    expect(items.map((i) => i.label)).toEqual(["Layout", "Visual style", "Spacing", "Gallery"]);
    const text = JSON.stringify(items);
    expect(text).not.toContain(base.rationale);
    for (const raw of ["artisan", "brand_derived", "tonal_shift", "featured_grid", "airy", "split"]) expect(text).not.toContain(raw);
  });

  it.each([
    ["compact", "More compact"],
    ["comfortable", "Balanced, as today"],
    ["airy", "More breathing room"],
  ] as const)("spacing %s → %s", (density, label) => {
    expect(summarizeDirection({ ...base, density }).find((i) => i.label === "Spacing")?.value).toBe(label);
  });

  it("gallery wording states a homepage limit, never deletion", () => {
    const gallery = summarizeDirection({ ...base, gallery: { maxItems: 6, layout: "grid" } }).find((i) => i.label === "Gallery");
    expect(gallery?.value).toBe("Showing up to 6 photos on the homepage");
    expect(gallery?.value).not.toMatch(/delet|remov/i);
  });

  it("covers every palette intent in owner language", () => {
    const style = (palette: WebsiteCreativeDirection["palette"]) =>
      summarizeDirection({ ...base, palette }).find((i) => i.label === "Visual style")?.value;
    expect(style({ mode: "brand" })).toContain("your brand colours");
    expect(style({ mode: "family" })).toContain("a fresh colour palette");
    for (const derivation of ["tonal_shift", "contrast_up", "muted", "vivid"] as const) {
      expect(style({ mode: "brand_derived", derivation })).toMatch(/take on your brand colours/);
    }
  });
});
