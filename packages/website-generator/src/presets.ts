import type { BusinessVertical } from "@generate-web-ai/business-config-types";

/**
 * Copy TEMPLATES only — section headings, generic CTAs, a generic
 * fallback subheading — never facts about a specific business. Nothing
 * here claims years of experience, ratings, certifications, or project
 * counts; those would be unverifiable claims about a real business this
 * generator has no basis to assert (see generateSiteConfig.ts's
 * docstring). A preset supplies chrome; BusinessConfig supplies facts.
 */
export interface WebsiteGeneratorPreset {
  /** Used as a generic hero subheading only when business_profile.description is absent. */
  heroSubheadingFallback: string;
  aboutHeading: string;
  servicesHeading: string;
  ctaHeading: string;
  ctaPrimaryLabel: string;
  contactHeading: string;
  formSubmitLabel: string;
}

export const homeRenovationPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Reformas integrales y servicios para el hogar.",
  aboutHeading: "Sobre nosotros",
  servicesHeading: "Nuestros servicios",
  ctaHeading: "¿Listo para empezar tu proyecto?",
  ctaPrimaryLabel: "Solicitar presupuesto",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar solicitud",
};

/** Used for any BusinessVertical without a dedicated preset yet — kept
 * intentionally generic (no industry-specific claims) rather than
 * throwing, so the generator supports every vertical from day one at a
 * baseline level while dedicated presets are added incrementally. */
export const genericPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "",
  aboutHeading: "Sobre nosotros",
  servicesHeading: "Nuestros servicios",
  ctaHeading: "¿Hablamos de tu proyecto?",
  ctaPrimaryLabel: "Contactar",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar",
};

const PRESETS: Partial<Record<BusinessVertical, WebsiteGeneratorPreset>> = {
  home_renovation: homeRenovationPreset,
};

export function getPreset(industry: BusinessVertical): WebsiteGeneratorPreset {
  return PRESETS[industry] ?? genericPreset;
}
