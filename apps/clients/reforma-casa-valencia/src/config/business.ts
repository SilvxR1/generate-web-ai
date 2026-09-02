// ReformaCasa Valencia — BusinessConfig. The structured source of truth
// for facts about the business itself: what generateSiteConfig() (see
// site.ts) derives brand/theme/services/SEO/contact facts from. Content
// that can't honestly be derived from a BusinessConfig yet (real
// photography, hand-written marketing copy, the demo gallery/
// testimonials/FAQ/process sections) stays in site.ts as an explicit
// override instead — see that file's comment for the split.
import type { BusinessConfig } from "@generate-web-ai/business-config-types";

export const businessConfig: BusinessConfig = {
  business_profile: {
    name: "ReformaCasa Valencia",
    slug: "reforma-casa-valencia",
    industry: "home_renovation",
    description:
      "Empresa de reformas en Valencia: reformas integrales, cocinas y baños con presupuesto sin compromiso.",
    location: {
      city: "Valencia",
      region: "Valencia",
      country: "ES",
      postal_code: "46006",
    },
    service_area: ["Valencia ciudad", "área metropolitana de Valencia"],
    services: [
      {
        id: "reforma-integral",
        name: "Reformas integrales",
        description:
          "Proyectos llave en mano: planificación, ejecución y coordinación de todos los gremios para transformar tu vivienda de principio a fin.",
        featured: true,
      },
      {
        id: "cocinas",
        name: "Cocinas",
        description:
          "Cocinas funcionales y actuales, con distribución optimizada, mobiliario a medida e instalaciones adaptadas a tu día a día.",
      },
      {
        id: "banos",
        name: "Baños",
        description:
          "Baños con acabados de calidad y soluciones de accesibilidad, cuidando la impermeabilización y el detalle en cada metro cuadrado.",
      },
      {
        id: "pintura",
        name: "Pintura",
        description: "Pintura interior y exterior con materiales de calidad, protección de superficies y un acabado impecable.",
      },
      {
        id: "electricidad-fontaneria",
        name: "Electricidad y fontanería",
        description: "Instalaciones eléctricas y de fontanería nuevas o actualizadas, siempre conforme a normativa.",
      },
      {
        id: "diseno-planificacion",
        name: "Diseño y planificación",
        description: "Asesoramiento en distribución, materiales y presupuesto antes de empezar, para que tomes decisiones con seguridad.",
      },
    ],
    target_customers: "Propietarios de vivienda en Valencia ciudad y área metropolitana.",
    contact: {
      phone: "+34 960 00 00 00",
      email: "info@reformacasavalencia.example",
      address: {
        street_address: "Carrer de Cadis, 15",
        locality: "Valencia",
        region: "Valencia",
        postal_code: "46006",
        country: "ES",
      },
    },
    business_hours: [
      { days: ["monday", "tuesday", "wednesday", "thursday", "friday"], opens: "09:00", closes: "14:00" },
      { days: ["monday", "tuesday", "wednesday", "thursday", "friday"], opens: "16:00", closes: "19:00" },
      { days: ["saturday"], opens: "10:00", closes: "13:00" },
    ],
  },
  brand: {
    tagline: "Reformas integrales en Valencia",
    colors: {
      primary: "#2A2420",
      secondary: "#8C8377",
      accent: "#A6572F",
      background: "#F7F2EA",
      foreground: "#2A2420",
    },
    typography: {
      sans: "'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
      display: "'Fraunces', Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', serif",
    },
  },
  website: {
    seo: {
      title: "ReformaCasa Valencia | Reformas integrales en Valencia",
      description:
        "Empresa de reformas en Valencia: reformas integrales, cocinas y baños con presupuesto sin compromiso. Solicita tu presupuesto hoy mismo.",
    },
  },
  lead_management: {
    enabled: true,
    sources: ["website_form", "phone"],
    required_fields: ["name", "phone", "email", "message"],
  },
};
