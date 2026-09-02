import type { ThemeConfig } from "@generate-web-ai/site-config";

// Used only when BusinessConfig.brand is absent — SiteConfig.theme is
// required, but BusinessConfig.brand is optional (a business hasn't
// necessarily defined a brand yet). A neutral, generic fallback, not
// specific to any industry or client.
export const DEFAULT_THEME: ThemeConfig = {
  colors: {
    primary: "#2563eb",
    secondary: "#0f766e",
    accent: "#f59e0b",
    background: "#ffffff",
    foreground: "#111827",
  },
  fonts: {
    sans: "Inter, system-ui, sans-serif",
  },
  radius: {
    base: "0.5rem",
    lg: "0.75rem",
  },
};
