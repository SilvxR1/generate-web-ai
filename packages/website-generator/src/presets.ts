import type { BusinessVertical } from "@generate-web-ai/business-config-types";
import type { DesignFamily } from "./design.ts";

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
  galleryHeading: string;
  ctaHeading: string;
  ctaPrimaryLabel: string;
  contactHeading: string;
  formSubmitLabel: string;
}

export const homeRenovationPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Reformas integrales y servicios para el hogar.",
  aboutHeading: "Sobre nosotros",
  servicesHeading: "Nuestros servicios",
  galleryHeading: "Nuestros proyectos",
  ctaHeading: "¿Listo para empezar tu proyecto?",
  ctaPrimaryLabel: "Solicitar presupuesto",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar solicitud",
};

/** Handmade/artisan, product- and gallery-led businesses (crafts,
 * boutique goods, ateliers). */
export const artisanPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Piezas hechas a mano, con cuidado en cada detalle.",
  aboutHeading: "Nuestra historia",
  servicesHeading: "Lo que hacemos",
  galleryHeading: "Nuestras creaciones",
  ctaHeading: "¿Tienes una idea en mente?",
  ctaPrimaryLabel: "Cuéntanosla",
  contactHeading: "Hablemos",
  formSubmitLabel: "Enviar mensaje",
};

/** Trades/construction — credibility and project proof first. */
export const constructionPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Servicios profesionales, hechos con solidez.",
  aboutHeading: "Sobre nosotros",
  servicesHeading: "Nuestros servicios",
  galleryHeading: "Proyectos realizados",
  ctaHeading: "¿Listo para empezar tu proyecto?",
  ctaPrimaryLabel: "Solicitar presupuesto",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar solicitud",
};

/** Clinics, agencies, B2B services — restrained, expertise-led. */
export const professionalServicesPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Servicios profesionales en los que puedes confiar.",
  aboutHeading: "Quiénes somos",
  servicesHeading: "Servicios",
  galleryHeading: "Nuestro trabajo",
  ctaHeading: "¿Hablamos de tu proyecto?",
  ctaPrimaryLabel: "Contactar",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar",
};

/** Restaurants, hotels — inviting, editorial. */
export const hospitalityPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "Una experiencia pensada para ti.",
  aboutHeading: "Nuestra historia",
  servicesHeading: "Qué ofrecemos",
  galleryHeading: "Un vistazo por dentro",
  ctaHeading: "Reserva tu visita",
  ctaPrimaryLabel: "Reservar",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar",
};

/** Used for any business without a dedicated preset yet — kept
 * intentionally generic (no industry-specific claims) rather than
 * throwing, so the generator supports every vertical from day one at a
 * baseline level while dedicated presets are added incrementally. */
export const genericPreset: WebsiteGeneratorPreset = {
  heroSubheadingFallback: "",
  aboutHeading: "Sobre nosotros",
  servicesHeading: "Nuestros servicios",
  galleryHeading: "Galería",
  ctaHeading: "¿Hablamos de tu proyecto?",
  ctaPrimaryLabel: "Contactar",
  contactHeading: "Contacto",
  formSubmitLabel: "Enviar",
};

const PRESETS_BY_VERTICAL: Partial<Record<BusinessVertical, WebsiteGeneratorPreset>> = {
  home_renovation: homeRenovationPreset,
};

const PRESETS_BY_FAMILY: Record<DesignFamily, WebsiteGeneratorPreset> = {
  artisan: artisanPreset,
  construction: constructionPreset,
  professional_services: professionalServicesPreset,
  hospitality: hospitalityPreset,
  generic: genericPreset,
};

/**
 * A specific vertical preset (when one exists, e.g. `home_renovation`)
 * wins outright over the broader design-family preset — more specific
 * real-world copy beats a family default. Otherwise falls back to the
 * family's preset, which is how every vertical gets sensible, non-generic
 * copy even without its own dedicated entry (Section 4: don't hardcode
 * the product to one vertical).
 */
export function getPreset(industry: BusinessVertical, family: DesignFamily = "generic"): WebsiteGeneratorPreset {
  return PRESETS_BY_VERTICAL[industry] ?? PRESETS_BY_FAMILY[family];
}
