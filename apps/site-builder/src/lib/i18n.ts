/**
 * C2.1 — the generated site's own chrome strings (navigation, footer,
 * consent banner, 404), per SiteConfig.locale. Business content never
 * comes from here; it is already in the SiteConfig. A SiteConfig without
 * a locale renders exactly as before ("en").
 */
import type { SiteConfig, SiteLocale } from "@generate-web-ai/site-config";

export interface ChromeStrings {
  htmlLang: string;
  ogLocale: string;
  mainNavLabel: string;
  menuLabel: string;
  legalNavLabel: string;
  legalLinks: ReadonlyArray<{ path: string; label: string }>;
  consentPreferences: string;
  consent: {
    text: string;
    necessary: string;
    analytics: string;
    reject: string;
    save: string;
    accept: string;
    dialogLabel: string;
  };
  notFound: { title: string; heading: string; body: string; home: string };
}

const STRINGS: Record<SiteLocale, ChromeStrings> = {
  en: {
    htmlLang: "en",
    ogLocale: "en_US",
    mainNavLabel: "Main",
    menuLabel: "Menu",
    legalNavLabel: "Legal",
    legalLinks: [
      { path: "/privacy", label: "Privacy Policy" },
      { path: "/terms", label: "Terms of Service" },
      { path: "/cookies", label: "Cookie Policy" },
    ],
    consentPreferences: "Manage cookie preferences",
    consent: {
      text:
        "This site stores in your browser only what it needs to work, such as your choice on this notice. " +
        "If you allow it, it also sends its own visit statistics, without cookies.",
      necessary: "Necessary (always on)",
      analytics: "Analytics",
      reject: "Reject non-essential",
      save: "Save preferences",
      accept: "Accept all",
      dialogLabel: "Cookie preferences",
    },
    notFound: {
      title: "Page not found",
      heading: "Page not found",
      body: "The page you are looking for doesn't exist.",
      home: "Go to the home page",
    },
  },
  es: {
    htmlLang: "es",
    ogLocale: "es_ES",
    mainNavLabel: "Principal",
    menuLabel: "Menú",
    legalNavLabel: "Información legal",
    legalLinks: [
      { path: "/aviso-legal", label: "Aviso legal" },
      { path: "/privacidad", label: "Privacidad" },
      { path: "/cookies", label: "Cookies" },
    ],
    consentPreferences: "Preferencias de privacidad",
    consent: {
      text:
        "Este sitio guarda en tu navegador solo lo necesario para funcionar, como tu elección sobre este aviso. " +
        "Si lo permites, también envía estadísticas de visitas propias, sin cookies.",
      necessary: "Imprescindible (siempre activo)",
      analytics: "Analítica",
      reject: "Rechazar opcionales",
      save: "Guardar selección",
      accept: "Aceptar todo",
      dialogLabel: "Preferencias de privacidad",
    },
    notFound: {
      title: "Página no encontrada",
      heading: "Página no encontrada",
      body: "La página que buscas no existe.",
      home: "Ir a la página de inicio",
    },
  },
};

export function chromeStrings(siteConfig: Pick<SiteConfig, "locale">): ChromeStrings {
  return STRINGS[siteConfig.locale === "es" ? "es" : "en"];
}

/** "/privacidad" -> "/privacidad/": the URL Cloudflare Pages finally serves
 * for a directory-format Astro build (it 308s the slashless form). */
export function canonicalPath(path: string): string {
  if (path === "/" || path === "") return "/";
  return path.endsWith("/") ? path : `${path}/`;
}

/** `siteUrl` as a bare https origin (no trailing slash), or undefined when
 * absent or not a plain https origin. */
export function canonicalOrigin(siteConfig: Pick<SiteConfig, "siteUrl">): string | undefined {
  const raw = siteConfig.siteUrl?.trim();
  if (!raw) return undefined;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.pathname.replace(/\/$/, "") !== "" || url.search || url.hash) return undefined;
    return url.origin;
  } catch {
    return undefined;
  }
}
