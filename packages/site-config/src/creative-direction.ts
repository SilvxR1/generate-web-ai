/**
 * WebsiteCreativeDirection (A8.2.1) — the canonical, provider-independent
 * contract for HOW a deterministic website presents a business's real
 * content: a finite vocabulary of presentation decisions a creative
 * provider's (internal or external) output is normalized into before it
 * ever reaches packages/website-generator.
 *
 * Lives here, in site-config, because it describes presentation of a
 * SiteConfig and is shared by every consumer that already depends on this
 * package (website-generator, Studio) without adding a new package or a
 * second copy of the type. apps/api mirrors it explicitly as
 * app.domain.creative.website_direction; fixtures/creative-direction.
 * conformance.json holds the one vocabulary + case set both
 * implementations are tested against, so neither can drift silently.
 *
 * Presentation ONLY, by construction: every field is a closed enum, a
 * bounded integer, or a fixed-order section key — except `rationale`, a
 * short plain-text audit note shown to the operator/owner (never rendered
 * into the generated site). There is deliberately no field that could
 * carry a business fact (name, services, prices, contact details, reviews,
 * claims), an asset URL/id, a font name, a colour value, CSS, or HTML —
 * WHAT content exists always comes from BusinessConfig and the business's
 * real assets; this decides only how that content is arranged and styled.
 *
 * Versioned: `version: "1"` is the only accepted value. A future
 * incompatible vocabulary becomes a new version with its own type in a
 * discriminated union, so a CreativeGeneration persisted under "1" is
 * always read with "1" semantics — its meaning can never change silently.
 */

export const WEBSITE_CREATIVE_DIRECTION_VERSION = "1" as const;

/** BrandStrategy (apps/api app.domain.enums.BrandStrategy) — how much of
 * the existing visual identity to keep. */
export const CREATIVE_STRATEGIES = ["preserve", "evolve", "new_direction"] as const;

/** The deterministic design families website-generator's design.ts
 * already implements (each has its own token set: palette, fonts, radius,
 * gallery placement, CTA emphasis, surfaces). */
export const WEBSITE_DESIGN_FAMILIES = [
  "artisan",
  "construction",
  "professional_services",
  "hospitality",
  "generic",
] as const;

/** Palette INTENT — colours are computed later by website-generator,
 * never supplied here:
 * - brand: the business's own brand colours, unchanged.
 * - brand_derived: computed from the brand colours via `derivation`.
 * - family: the design family's own palette (ignores brand colours). */
export const PALETTE_MODES = ["brand", "brand_derived", "family"] as const;
export const PALETTE_DERIVATIONS = ["tonal_shift", "contrast_up", "muted", "vivid"] as const;

/** Each pairing is one of the safe, no-remote-font stacks
 * website-generator's design families already ship:
 * - modern_sans: Inter / system-ui (generic)
 * - system_sans: native system UI stack (professional_services)
 * - humanist_serif_display: humanist sans body + serif display (artisan)
 * - bold_display_sans: system sans body + heavy sans display (construction)
 * - classic_serif: serif body + serif display (hospitality) */
export const TYPOGRAPHY_PAIRINGS = [
  "modern_sans",
  "system_sans",
  "humanist_serif_display",
  "bold_display_sans",
  "classic_serif",
] as const;

/** sharp ≈ 0.25/0.375rem, soft ≈ 0.5/0.75rem, round ≈ 1/1.5rem — the
 * range the existing families already span. */
export const RADIUS_SCALES = ["sharp", "soft", "round"] as const;

/** Vertical section rhythm; "comfortable" is today's spacing. */
export const DENSITY_SCALES = ["compact", "comfortable", "airy"] as const;

/** The only sections whose relative order a direction may change. The
 * hero is always first and the cta/contact conversion pair always last;
 * sections the generator never produces (testimonials, faq, process —
 * they would need content it must not invent) are not in the vocabulary
 * at all. A section the business doesn't have is simply skipped. */
export const MOVABLE_SECTIONS = ["services", "gallery", "about"] as const;

/** split: text beside the real hero photo; centered: text centered with
 * the photo below/behind — the two layouts Hero.astro already renders
 * (today chosen by whether an image exists). */
export const HERO_LAYOUTS = ["split", "centered"] as const;

/** grid: uniform grid (today); featured_grid: the first real photo
 * rendered larger via Gallery.astro's existing `featured` item support. */
export const GALLERY_LAYOUTS = ["grid", "featured_grid"] as const;
export const GALLERY_MAX_ITEMS_MIN = 3;
export const GALLERY_MAX_ITEMS_MAX = 24;

export const SURFACE_MODES = ["alternate", "flat"] as const;
export const CTA_VARIANTS = ["default", "emphasis"] as const;

export const RATIONALE_MAX_LENGTH = 280;

export type CreativeStrategy = (typeof CREATIVE_STRATEGIES)[number];
export type WebsiteDesignFamily = (typeof WEBSITE_DESIGN_FAMILIES)[number];
export type PaletteMode = (typeof PALETTE_MODES)[number];
export type PaletteDerivation = (typeof PALETTE_DERIVATIONS)[number];
export type TypographyPairing = (typeof TYPOGRAPHY_PAIRINGS)[number];
export type RadiusScale = (typeof RADIUS_SCALES)[number];
export type DensityScale = (typeof DENSITY_SCALES)[number];
export type MovableSection = (typeof MOVABLE_SECTIONS)[number];
export type HeroLayout = (typeof HERO_LAYOUTS)[number];
export type GalleryLayout = (typeof GALLERY_LAYOUTS)[number];
export type SurfaceMode = (typeof SURFACE_MODES)[number];
export type CtaVariant = (typeof CTA_VARIANTS)[number];

export type PaletteDirection =
  | { mode: "brand" }
  | { mode: "brand_derived"; derivation: PaletteDerivation }
  | { mode: "family" };

export interface WebsiteCreativeDirection {
  version: typeof WEBSITE_CREATIVE_DIRECTION_VERSION;
  strategy: CreativeStrategy;
  family: WebsiteDesignFamily;
  palette: PaletteDirection;
  typography: { pairing: TypographyPairing };
  radius: RadiusScale;
  density: DensityScale;
  /** A full permutation of MOVABLE_SECTIONS — never a subset, so a
   * direction can reorder real content but can never hide it. */
  sectionOrder: MovableSection[];
  hero: { layout: HeroLayout };
  gallery: { maxItems: number; layout: GalleryLayout };
  surfaces: { mode: SurfaceMode };
  cta: { variant: CtaVariant };
  /** Plain-text audit note ("why this direction"), shown to the owner/
   * operator only — never rendered into the generated site. */
  rationale: string;
}

export type WebsiteCreativeDirectionValidation =
  | { ok: true; value: WebsiteCreativeDirection }
  | { ok: false; errors: string[] };

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && (values as readonly string[]).includes(value);
}

function checkKeys(errors: string[], path: string, value: Json, allowed: readonly string[]): void {
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) errors.push(`${path}.${key}: unknown field (presentation contract forbids extra keys)`);
  }
}

function checkEnum(errors: string[], path: string, values: readonly string[], value: unknown): void {
  if (!oneOf(values, value)) errors.push(`${path}: must be one of ${values.join(", ")}`);
}

function checkNested(errors: string[], path: string, value: unknown, field: string, values: readonly string[]): void {
  if (!isObject(value)) {
    errors.push(`${path}: must be an object`);
    return;
  }
  checkKeys(errors, path, value, [field]);
  checkEnum(errors, `${path}.${field}`, values, value[field]);
}

const TOP_LEVEL_KEYS = [
  "version",
  "strategy",
  "family",
  "palette",
  "typography",
  "radius",
  "density",
  "sectionOrder",
  "hero",
  "gallery",
  "surfaces",
  "cta",
  "rationale",
] as const;

// Any C0 control character or DEL — rationale is single-line plain text.
const CONTROL_CHARACTERS = new RegExp("[\\u0000-\\u001f\\u007f]");

/** Runtime validation for untrusted input (a persisted CreativeGeneration,
 * an API response). Mirrors apps/api's Pydantic model rule for rule —
 * see fixtures/creative-direction.conformance.json. */
export function validateWebsiteCreativeDirection(input: unknown): WebsiteCreativeDirectionValidation {
  const errors: string[] = [];
  if (!isObject(input)) return { ok: false, errors: ["direction: must be an object"] };

  checkKeys(errors, "direction", input, TOP_LEVEL_KEYS);
  for (const key of TOP_LEVEL_KEYS) {
    if (!(key in input)) errors.push(`direction.${key}: required`);
  }

  if (input.version !== WEBSITE_CREATIVE_DIRECTION_VERSION) {
    errors.push(`direction.version: unsupported version (expected "${WEBSITE_CREATIVE_DIRECTION_VERSION}")`);
  }
  checkEnum(errors, "direction.strategy", CREATIVE_STRATEGIES, input.strategy);
  checkEnum(errors, "direction.family", WEBSITE_DESIGN_FAMILIES, input.family);

  const palette = input.palette;
  if (!isObject(palette)) {
    errors.push("direction.palette: must be an object");
  } else {
    checkEnum(errors, "direction.palette.mode", PALETTE_MODES, palette.mode);
    if (palette.mode === "brand_derived") {
      checkKeys(errors, "direction.palette", palette, ["mode", "derivation"]);
      checkEnum(errors, "direction.palette.derivation", PALETTE_DERIVATIONS, palette.derivation);
    } else {
      checkKeys(errors, "direction.palette", palette, ["mode"]);
    }
    if (input.strategy === "preserve" && palette.mode !== "brand") {
      errors.push('direction.palette.mode: a "preserve" direction must keep the brand palette');
    }
  }

  checkNested(errors, "direction.typography", input.typography, "pairing", TYPOGRAPHY_PAIRINGS);
  checkEnum(errors, "direction.radius", RADIUS_SCALES, input.radius);
  checkEnum(errors, "direction.density", DENSITY_SCALES, input.density);

  const order = input.sectionOrder;
  if (!Array.isArray(order)) {
    errors.push("direction.sectionOrder: must be an array");
  } else {
    order.forEach((section, index) => checkEnum(errors, `direction.sectionOrder[${index}]`, MOVABLE_SECTIONS, section));
    const isPermutation =
      order.length === MOVABLE_SECTIONS.length && MOVABLE_SECTIONS.every((section) => order.includes(section));
    if (!isPermutation) {
      errors.push(`direction.sectionOrder: must list each of ${MOVABLE_SECTIONS.join(", ")} exactly once`);
    }
  }

  checkNested(errors, "direction.hero", input.hero, "layout", HERO_LAYOUTS);

  const gallery = input.gallery;
  if (!isObject(gallery)) {
    errors.push("direction.gallery: must be an object");
  } else {
    checkKeys(errors, "direction.gallery", gallery, ["maxItems", "layout"]);
    const maxItems = gallery.maxItems;
    if (
      typeof maxItems !== "number" ||
      !Number.isInteger(maxItems) ||
      maxItems < GALLERY_MAX_ITEMS_MIN ||
      maxItems > GALLERY_MAX_ITEMS_MAX
    ) {
      errors.push(`direction.gallery.maxItems: must be an integer from ${GALLERY_MAX_ITEMS_MIN} to ${GALLERY_MAX_ITEMS_MAX}`);
    }
    checkEnum(errors, "direction.gallery.layout", GALLERY_LAYOUTS, gallery.layout);
  }

  checkNested(errors, "direction.surfaces", input.surfaces, "mode", SURFACE_MODES);
  checkNested(errors, "direction.cta", input.cta, "variant", CTA_VARIANTS);

  const rationale = input.rationale;
  if (typeof rationale !== "string" || rationale.trim().length === 0) {
    errors.push("direction.rationale: must be a non-empty string");
  } else {
    if (rationale.length > RATIONALE_MAX_LENGTH) {
      errors.push(`direction.rationale: must be at most ${RATIONALE_MAX_LENGTH} characters`);
    }
    if (/[<>]/.test(rationale) || CONTROL_CHARACTERS.test(rationale)) {
      errors.push("direction.rationale: must be plain single-line text (no markup or control characters)");
    }
  }

  return errors.length > 0 ? { ok: false, errors } : { ok: true, value: input as unknown as WebsiteCreativeDirection };
}
