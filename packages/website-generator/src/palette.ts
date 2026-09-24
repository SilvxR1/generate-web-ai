/**
 * Deterministic palette derivation (A8.2.3) for a WebsiteCreativeDirection's
 * `palette: { mode: "brand_derived", derivation }`. It is pure (no AI, no
 * randomness) and works in HSL on the business's own brand colours. It
 * returns hex colours and never CSS from anywhere else.
 *
 * Only hex brand colours (#rgb / #rrggbb) can be derived. Anything else
 * (a named colour, rgb(), a var()) returns `undefined` and the caller keeps
 * the brand palette unchanged rather than guessing.
 *
 * After derivation the foreground is checked against the background. If
 * their contrast ratio is below 4.5:1 (the WCAG AA body-text threshold) it
 * is replaced with whichever of a near-black or white reaches it. Only that
 * pair is guaranteed; button/accent contrast is not claimed here.
 */
import type { PaletteDerivation, ThemeColorConfig } from "@generate-web-ai/site-config";

interface Hsl {
  h: number;
  s: number;
  l: number;
}

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

function parseHex(value: string): [number, number, number] | undefined {
  const match = HEX.exec(value.trim());
  if (!match?.[1]) return undefined;
  const hex = match[1].length === 3 ? [...match[1]].map((c) => c + c).join("") : match[1];
  return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function toHsl([r, g, b]: [number, number, number]): Hsl {
  const [rn, gn, bn] = [r / 255, g / 255, b / 255];
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h =
    max === rn ? ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6 : max === gn ? ((bn - rn) / d + 2) / 6 : ((rn - gn) / d + 4) / 6;
  return { h, s, l };
}

function toHex({ h, s, l }: Hsl): string {
  const hue = (p: number, q: number, t: number): number => {
    const tt = t < 0 ? t + 1 : t > 1 ? t - 1 : t;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  let rgb: number[];
  if (s === 0) {
    rgb = [l, l, l];
  } else {
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    rgb = [hue(p, q, h + 1 / 3), hue(p, q, h), hue(p, q, h - 1 / 3)];
  }
  return `#${rgb.map((c) => Math.round(Math.min(1, Math.max(0, c)) * 255).toString(16).padStart(2, "0")).join("")}`;
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

function adjust(color: Hsl, { s, l }: { s?: (v: number) => number; l?: (v: number) => number }): Hsl {
  return { h: color.h, s: clamp01(s ? s(color.s) : color.s), l: clamp01(l ? l(color.l) : color.l) };
}

function relativeLuminance(hex: string): number {
  const rgb = parseHex(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const [la, lb] = [relativeLuminance(a), relativeLuminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const DARK_TEXT = "#111827";
const LIGHT_TEXT = "#ffffff";

function readableForeground(foreground: string, background: string): string {
  if (contrastRatio(foreground, background) >= 4.5) return foreground;
  return contrastRatio(DARK_TEXT, background) >= contrastRatio(LIGHT_TEXT, background) ? DARK_TEXT : LIGHT_TEXT;
}

type Channel = keyof ThemeColorConfig;

const RULES: Record<PaletteDerivation, Record<Channel, (c: Hsl) => Hsl>> = {
  // A lighter, softer version of the same brand: same hues.
  tonal_shift: {
    primary: (c) => adjust(c, { l: (l) => l + (1 - l) * 0.18, s: (s) => s * 0.9 }),
    secondary: (c) => adjust(c, { l: (l) => l + (1 - l) * 0.18, s: (s) => s * 0.9 }),
    accent: (c) => adjust(c, { l: (l) => l + (1 - l) * 0.12 }),
    background: (c) => adjust(c, { l: () => 0.975, s: (s) => Math.min(s, 0.35) }),
    foreground: (c) => adjust(c, { l: (l) => Math.min(l, 0.2) }),
  },
  // Deeper brand hues on a clean near-white ground.
  contrast_up: {
    primary: (c) => adjust(c, { l: (l) => l * 0.72, s: (s) => s + (1 - s) * 0.1 }),
    secondary: (c) => adjust(c, { l: (l) => l * 0.72 }),
    accent: (c) => adjust(c, { l: (l) => Math.min(l, 0.45), s: (s) => s + (1 - s) * 0.15 }),
    background: (c) => adjust(c, { l: () => 0.99, s: () => 0.2 }),
    foreground: (c) => adjust(c, { l: () => 0.1, s: (s) => Math.min(s, 0.3) }),
  },
  // Desaturated, calm version of the brand.
  muted: {
    primary: (c) => adjust(c, { s: (s) => s * 0.5 }),
    secondary: (c) => adjust(c, { s: (s) => s * 0.5 }),
    accent: (c) => adjust(c, { s: (s) => s * 0.6 }),
    background: (c) => adjust(c, { l: () => 0.965, s: () => 0.12 }),
    foreground: (c) => adjust(c, { l: (l) => Math.min(l, 0.22), s: (s) => s * 0.5 }),
  },
  // Saturated, mid-lightness version of the brand.
  vivid: {
    primary: (c) => adjust(c, { s: (s) => Math.min(1, s * 1.3 + 0.1), l: (l) => Math.min(0.55, Math.max(0.4, l)) }),
    secondary: (c) => adjust(c, { s: (s) => Math.min(1, s * 1.2 + 0.05) }),
    accent: (c) => adjust(c, { s: (s) => Math.min(1, s * 1.35 + 0.15), l: (l) => Math.min(0.55, Math.max(0.42, l)) }),
    background: (c) => adjust(c, { l: () => 0.985, s: () => 0.25 }),
    foreground: (c) => adjust(c, { l: (l) => Math.min(l, 0.15) }),
  },
};

const CHANNELS: Channel[] = ["primary", "secondary", "accent", "background", "foreground"];

/** Derives a palette from the business's brand colours, or returns
 * `undefined` if any brand colour isn't a hex value it can safely derive from. */
export function deriveBrandPalette(brand: ThemeColorConfig, derivation: PaletteDerivation): ThemeColorConfig | undefined {
  const parsed = CHANNELS.map((channel) => parseHex(brand[channel]));
  if (parsed.some((rgb) => rgb === undefined)) return undefined;
  const rules = RULES[derivation];
  const derived = Object.fromEntries(
    CHANNELS.map((channel, index) => [channel, toHex(rules[channel](toHsl(parsed[index]!)))]),
  ) as unknown as ThemeColorConfig;
  return { ...derived, foreground: readableForeground(derived.foreground, derived.background) };
}
