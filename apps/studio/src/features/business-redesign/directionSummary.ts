import type { WebsiteCreativeDirection } from "@generate-web-ai/site-config";

/** A8.2.5: plain-language summary of a stored, already-validated
 * WebsiteCreativeDirection for the owner-facing "What changed" panel.
 * Pure translation only: it never invents an explanation (the rationale
 * shown is the direction's own stored `rationale`) and never exposes
 * contract enum names such as "hospitality" or "brand_derived". */

export type ProposalMode = "refresh" | "new_direction" | "preserve";

export const MODE_LABELS: Record<ProposalMode, string> = {
  refresh: "Refresh",
  new_direction: "New direction",
  preserve: "Keep current design",
};

export function proposalMode(direction: WebsiteCreativeDirection): ProposalMode {
  if (direction.strategy === "evolve") return "refresh";
  if (direction.strategy === "new_direction") return "new_direction";
  return "preserve";
}

const STYLE_LABELS: Record<WebsiteCreativeDirection["family"], string> = {
  artisan: "Warm, handcrafted look",
  construction: "Solid, structured look",
  professional_services: "Clean, professional look",
  hospitality: "Classic, editorial look",
  generic: "Clean, modern look",
};

function paletteLabel(palette: WebsiteCreativeDirection["palette"]): string {
  if (palette.mode === "brand") return "your brand colours";
  if (palette.mode === "family") return "a fresh colour palette";
  const derived: Record<typeof palette.derivation, string> = {
    tonal_shift: "a lighter take on your brand colours",
    contrast_up: "a bolder, higher-contrast take on your brand colours",
    muted: "a softer take on your brand colours",
    vivid: "a more vivid take on your brand colours",
  };
  return derived[palette.derivation];
}

function layoutLabel(direction: WebsiteCreativeDirection): string {
  const hero =
    direction.hero.layout === "centered" ? "Headline centered above your main photo" : "Headline beside your main photo";
  const first = direction.sectionOrder[0];
  const lead =
    first === "about" ? "your story comes first" : first === "gallery" ? "your photos come first" : "your services come first";
  return `${hero}; ${lead}`;
}

const SPACING_LABELS: Record<WebsiteCreativeDirection["density"], string> = {
  compact: "More compact",
  comfortable: "Balanced, as today",
  airy: "More breathing room",
};

function galleryLabel(gallery: WebsiteCreativeDirection["gallery"]): string {
  const base = `Showing up to ${gallery.maxItems} photos on the homepage`;
  return gallery.layout === "featured_grid" ? `${base}, led by a larger featured photo` : base;
}

export interface DirectionSummaryItem {
  label: string;
  value: string;
}

export function summarizeDirection(direction: WebsiteCreativeDirection): DirectionSummaryItem[] {
  return [
    { label: "Layout", value: layoutLabel(direction) },
    { label: "Visual style", value: `${STYLE_LABELS[direction.family]} with ${paletteLabel(direction.palette)}` },
    { label: "Spacing", value: SPACING_LABELS[direction.density] },
    { label: "Gallery", value: galleryLabel(direction.gallery) },
  ];
}
