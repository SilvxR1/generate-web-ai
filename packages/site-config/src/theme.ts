export interface ThemeColorConfig {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  foreground: string;
}

export interface ThemeFontConfig {
  sans: string;
}

export interface ThemeRadiusConfig {
  base: string;
  lg: string;
}

export interface ThemeConfig {
  colors: ThemeColorConfig;
  fonts: ThemeFontConfig;
  radius: ThemeRadiusConfig;
}
