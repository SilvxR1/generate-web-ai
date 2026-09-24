export interface ThemeColorConfig {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  foreground: string;
}

export interface ThemeFontConfig {
  sans: string;
  /**
   * Optional editorial/statement typeface for display headings (hero,
   * section leads) — maps to `--ui-font-display`. Falls back to `sans`
   * (both in the CSS variable's own fallback chain and visually) when
   * omitted, so existing configs with no `display` font keep rendering
   * exactly as before.
   */
  display?: string;
}

export interface ThemeRadiusConfig {
  base: string;
  lg: string;
}

/** Vertical section rhythm (A8.2.3): CSS lengths for the
 * `--ui-space-section-sm/md/lg` tokens every block's padding already reads.
 * Omitted means each block's own built-in spacing, which is today's rhythm. */
export interface ThemeSpacingConfig {
  sectionSm: string;
  sectionMd: string;
  sectionLg: string;
}

export interface ThemeConfig {
  colors: ThemeColorConfig;
  fonts: ThemeFontConfig;
  radius: ThemeRadiusConfig;
  spacing?: ThemeSpacingConfig;
}
