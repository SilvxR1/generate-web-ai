// ReformaCasa Valencia — SiteConfig. This file is the single source of
// truth for the client's brand, theme, and page content: PageRenderer
// (from @generate-web-ai/renderer) turns `siteConfig.pages` into rendered
// blocks, and Layout.astro applies `siteConfig.theme`/`siteConfig.brand` to
// the page shell. Nothing about ReformaCasa Valencia is hardcoded into
// markup outside this file and the app shell (Header/Footer/Layout).
import type { AssetConfig, LocalBusinessConfig, SiteConfig } from "@generate-web-ai/site-config";

import heroImg from "../assets/hero/hero-mediterranean-living-room.jpg";
import servicioIntegralImg from "../assets/services/reforma-integral.jpg";
import servicioCocinasImg from "../assets/services/cocinas.jpg";
import servicioBanosImg from "../assets/services/banos.jpg";
import servicioPinturaImg from "../assets/services/pintura.jpg";
import servicioInstalacionesImg from "../assets/services/electricidad-fontaneria.jpg";
import servicioDisenoImg from "../assets/services/diseno-planificacion.jpg";
import ruzafaImg from "../assets/projects/ruzafa-reforma-integral.jpg";
import plaDelRealImg from "../assets/projects/pla-del-real-cocina.jpg";
import patraixImg from "../assets/projects/patraix-detalle-materiales.jpg";
import campanarBeforeImg from "../assets/projects/campanar-bano-before.jpg";
import campanarAfterImg from "../assets/projects/campanar-bano-after.jpg";
import benimacletImg from "../assets/projects/benimaclet-vivienda.jpg";
import eixampleImg from "../assets/projects/eixample-interior.jpg";

/**
 * Wraps an imported local image (ImageMetadata) as a typed AssetConfig.
 * Passes the image object through as `src` rather than flattening it to
 * `image.src` — `@generate-web-ai/ui`'s `Media` component needs the whole
 * object (width/height/format) to generate a real responsive `srcset` via
 * `astro:assets`; a bare string loses that and falls back to an
 * unoptimized `<img>`.
 */
function asset(image: ImageMetadata, alt: string): AssetConfig {
  return { src: image, alt };
}

/**
 * Structured business/contact data. Every value here is FICTITIOUS demo
 * content (an invented Valencia address and a typical Spanish split
 * schedule) — see IMAGE-SOURCES.md for the same disclosure already made
 * about the gallery/testimonials content. This is the single source for
 * both the on-page contact details below and the schema.org `LocalBusiness`
 * JSON-LD emitted from `Layout.astro`.
 */
const business: LocalBusinessConfig = {
  telephone: "+34 960 00 00 00",
  email: "info@reformacasavalencia.example",
  address: {
    streetAddress: "Carrer de Cadis, 15",
    addressLocality: "Valencia",
    addressRegion: "Valencia",
    postalCode: "46006",
    addressCountry: "ES",
  },
  openingHours: [
    { dayOfWeek: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], opens: "09:00", closes: "14:00" },
    { dayOfWeek: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], opens: "16:00", closes: "19:00" },
    { dayOfWeek: ["Saturday"], opens: "10:00", closes: "13:00" },
  ],
  priceRange: "€€",
};

const PHONE_HREF = `tel:${business.telephone!.replace(/\s+/g, "")}`;

export const siteConfig: SiteConfig = {
  brand: {
    name: "ReformaCasa Valencia",
    tagline: "Reformas integrales en Valencia",
  },
  theme: {
    colors: {
      primary: "#2A2420",
      secondary: "#8C8377",
      accent: "#A6572F",
      background: "#F7F2EA",
      foreground: "#2A2420",
    },
    fonts: {
      sans: "'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
      display: "'Fraunces', Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', serif",
    },
    radius: {
      base: "0.375rem",
      lg: "0.625rem",
    },
  },
  business,
  features: {
    contactForm: true,
    chatbot: false,
    booking: false,
  },
  seo: {
    title: "ReformaCasa Valencia | Reformas integrales en Valencia",
    description:
      "Empresa de reformas en Valencia: reformas integrales, cocinas y baños con presupuesto sin compromiso. Solicita tu presupuesto hoy mismo.",
    ogImage: asset(heroImg, "Salón mediterráneo con chimenea de piedra, suelo de madera y luz natural cálida"),
  },
  pages: [
    {
      path: "/",
      seo: {
        title: "ReformaCasa Valencia — Reformas integrales, cocinas y baños en Valencia",
        description:
          "Reformas integrales, de cocinas y de baños en Valencia. Presupuesto sin compromiso, garantía de obra y un equipo que cuida cada detalle.",
        ogImage: asset(heroImg, "Salón mediterráneo con chimenea de piedra, suelo de madera y luz natural cálida"),
      },
      blocks: [
        {
          type: "hero",
          id: "inicio",
          content: {
            eyebrow: "Reformas en Valencia",
            heading: "Transformamos espacios para vivirlos mejor.",
            subheading:
              "Reformas integrales y parciales en Valencia, con un equipo que cuida cada detalle desde la primera visita hasta la entrega final.",
            primaryAction: { label: "Pedir presupuesto", href: "#contacto" },
            secondaryAction: { label: "Ver proyectos", href: "#proyectos", variant: "outline" },
            image: asset(heroImg, "Salón de estilo mediterráneo con chimenea de piedra, vigas de madera y luz natural cálida"),
            stat: { value: "+10", label: "años de experiencia en Valencia" },
          },
        },
        {
          type: "features",
          id: "por-que-elegirnos",
          background: "surface",
          content: {
            heading: "Por qué elegir ReformaCasa Valencia",
            subheading: "Un equipo local que acompaña tu reforma de principio a fin.",
            items: [
              {
                title: "+10 años de experiencia",
                description: "Más de una década reformando viviendas en Valencia y su área metropolitana.",
              },
              {
                title: "Presupuesto sin compromiso",
                description: "Visitamos tu vivienda y te entregamos un presupuesto detallado, sin coste ni compromiso.",
              },
              {
                title: "Garantía de obra",
                description: "Todas nuestras reformas cuentan con garantía sobre los trabajos ejecutados.",
              },
              {
                title: "Equipo profesional",
                description: "Oficiales especializados en cada gremio, coordinados por un único responsable de obra.",
              },
              {
                title: "Atención personalizada",
                description: "Un mismo interlocutor te acompaña durante toda la reforma, de la visita a la entrega.",
              },
              {
                title: "Servicio integral en Valencia",
                description: "Cubrimos capital y área metropolitana, desde reformas parciales hasta proyectos integrales.",
              },
            ],
          },
        },
        {
          type: "services",
          id: "servicios",
          content: {
            heading: "Nuestros servicios",
            subheading: "Reformas integrales y por especialidad, adaptadas a cada vivienda.",
            items: [
              {
                title: "Reformas integrales",
                description:
                  "Proyectos llave en mano: planificación, ejecución y coordinación de todos los gremios para transformar tu vivienda de principio a fin.",
                image: asset(servicioIntegralImg, "Interior cálido con maderas naturales y detalles en mármol tras una reforma integral"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
                featured: true,
              },
              {
                title: "Cocinas",
                description:
                  "Cocinas funcionales y actuales, con distribución optimizada, mobiliario a medida e instalaciones adaptadas a tu día a día.",
                image: asset(servicioCocinasImg, "Cocina moderna con mobiliario de madera curvo y encimera de mármol"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              },
              {
                title: "Baños",
                description:
                  "Baños con acabados de calidad y soluciones de accesibilidad, cuidando la impermeabilización y el detalle en cada metro cuadrado.",
                image: asset(servicioBanosImg, "Baño moderno con lavabo de hormigón y espejo con arco"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              },
              {
                title: "Pintura",
                description: "Pintura interior y exterior con materiales de calidad, protección de superficies y un acabado impecable.",
                image: asset(servicioPinturaImg, "Muestras de color de pintura aplicadas sobre una pared antes de elegir el tono final"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              },
              {
                title: "Electricidad y fontanería",
                description: "Instalaciones eléctricas y de fontanería nuevas o actualizadas, siempre conforme a normativa.",
                image: asset(servicioInstalacionesImg, "Red de tuberías e instalaciones eléctricas y de fontanería"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              },
              {
                title: "Diseño y planificación",
                description: "Asesoramiento en distribución, materiales y presupuesto antes de empezar, para que tomes decisiones con seguridad.",
                image: asset(servicioDisenoImg, "Planos arquitectónicos extendidos sobre una mesa de trabajo"),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              },
            ],
          },
        },
        {
          type: "process",
          id: "proceso",
          background: "surface",
          content: {
            heading: "Cómo trabajamos",
            subheading: "Un proceso claro y ordenado, para que sepas qué esperar en cada fase.",
            steps: [
              {
                title: "Primera visita",
                description: "Visitamos tu vivienda, escuchamos lo que necesitas y valoramos el alcance de la reforma sobre el terreno.",
              },
              {
                title: "Propuesta y presupuesto",
                description: "Te entregamos una propuesta detallada con partidas, plazos y presupuesto cerrado, sin sorpresas.",
              },
              {
                title: "Ejecución de la reforma",
                description: "Coordinamos a todos los gremios y te mantenemos informado del avance durante toda la obra.",
              },
              {
                title: "Entrega y garantía",
                description: "Revisamos cada detalle contigo antes de la entrega y respaldamos el trabajo con garantía de obra.",
              },
            ],
          },
        },
        {
          type: "gallery",
          id: "proyectos",
          content: {
            heading: "Proyectos de reforma",
            subheading:
              "Una muestra de nuestro estilo de trabajo en distintos barrios de Valencia. Proyectos ilustrativos creados para esta demostración, no corresponden a viviendas ni clientes reales.",
            items: [
              {
                title: "Reforma integral en Ruzafa",
                category: "Reforma integral",
                image: asset(ruzafaImg, "Salón elegante con ventana en arco, sofás y mesa de centro de madera"),
                description: "Reforma completa de una vivienda de 90 m², renovando distribución, instalaciones y acabados.",
                link: { label: "Ver detalles", href: "#contacto" },
                featured: true,
              },
              {
                title: "Cocina contemporánea en El Pla del Real",
                category: "Cocinas",
                image: asset(plaDelRealImg, "Cocina contemporánea en madera cálida con encimera de mármol"),
                description: "Cocina abierta al salón con isla central, mobiliario a medida y electrodomésticos integrados.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
              {
                title: "Baño mediterráneo en Campanar",
                category: "Baños",
                image: asset(campanarAfterImg, "Baño reformado en Campanar con piedra natural y grifería negra"),
                description: "Renovación completa de baño con ducha a ras de suelo y revestimiento cerámico artesanal.",
                beforeAfter: {
                  before: asset(campanarBeforeImg, "Baño antiguo en Campanar con azulejo desgastado antes de la reforma"),
                  after: asset(campanarAfterImg, "Baño reformado en Campanar con piedra natural, espejo con marco y grifería negra"),
                  beforeLabel: "Antes",
                  afterLabel: "Después",
                },
              },
              {
                title: "Reforma de vivienda en Benimaclet",
                category: "Reforma integral",
                image: asset(benimacletImg, "Salón y comedor de planta abierta tras una reforma integral"),
                description: "Puesta al día de una vivienda de los años 80, ganando luz natural y espacios diáfanos.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
              {
                title: "Detalle de materiales en Patraix",
                category: "Cocinas",
                image: asset(patraixImg, "Selección de muestras de madera y piedra natural para una reforma de cocina"),
                description: "Selección de materiales naturales para una cocina abierta con mobiliario a medida.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
              {
                title: "Reforma integral en L'Eixample",
                category: "Reforma integral",
                image: asset(eixampleImg, "Salón moderno y luminoso con sofás claros y chimenea"),
                description: "Reforma integral con optimización de distribución y mejora de la eficiencia energética.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
            ],
          },
        },
        {
          type: "testimonials",
          id: "opiniones",
          background: "surface",
          content: {
            heading: "Lo que dicen quienes han confiado en nosotros",
            subheading: "Opiniones de ejemplo, creadas para esta demostración.",
            items: [
              {
                quote:
                  "Desde la primera visita nos explicaron todo el proceso con claridad. La obra terminó en el plazo acordado y el resultado superó lo que esperábamos.",
                author: "Marta Ibáñez",
                role: "Ruzafa, Valencia",
                rating: 5,
                featured: true,
              },
              {
                quote:
                  "Cuidaron cada detalle, mantuvieron la casa limpia durante toda la reforma y nos avisaban de cualquier cambio antes de hacerlo. Muy buena comunicación.",
                author: "Javier Soler",
                role: "El Pla del Real, Valencia",
                rating: 5,
              },
              {
                quote: "La cocina quedó exactamente como la habíamos imaginado. El equipo fue puntual, ordenado y muy profesional en todo momento.",
                author: "Lucía Ferrer",
                role: "Patraix, Valencia",
                rating: 5,
              },
            ],
          },
        },
        {
          type: "faq",
          id: "preguntas-frecuentes",
          content: {
            heading: "Preguntas frecuentes",
            items: [
              {
                question: "¿Cuánto cuesta una reforma?",
                answer:
                  "El coste depende del alcance, los materiales y el estado de partida de la vivienda. Tras la primera visita te entregamos un presupuesto detallado y cerrado, sin sorpresas.",
              },
              {
                question: "¿Cuánto dura una reforma?",
                answer:
                  "Una reforma parcial puede completarse en pocas semanas, mientras que una reforma integral suele necesitar varios meses. Te damos una estimación de plazos en la propuesta inicial.",
              },
              {
                question: "¿Os encargáis de todo el proyecto?",
                answer:
                  "Sí. Coordinamos todos los gremios necesarios (albañilería, electricidad, fontanería, pintura...) bajo un único responsable de obra, para que no tengas que gestionar proveedores por separado.",
              },
              {
                question: "¿Puedo reformar solo una habitación?",
                answer: "Sí, trabajamos tanto reformas integrales como parciales: una cocina, un baño o cualquier estancia concreta de la vivienda.",
              },
              {
                question: "¿El presupuesto incluye todos los detalles?",
                answer: "Sí, nuestro presupuesto detalla materiales, partidas y plazos antes de comenzar la obra, para que sepas exactamente qué incluye.",
              },
              {
                question: "¿Trabajáis en toda Valencia?",
                answer: "Sí, trabajamos en la ciudad de Valencia y su área metropolitana. Cuéntanos dónde está tu vivienda y te confirmamos la cobertura.",
              },
            ],
          },
        },
        {
          type: "cta",
          content: {
            heading: "¿Tienes un proyecto en mente?",
            subheading: "Cuéntanos qué quieres transformar y te ayudaremos a dar el primer paso.",
            primaryAction: { label: "Pedir presupuesto", href: "#contacto" },
            secondaryAction: { label: "Llamar ahora", href: PHONE_HREF, variant: "outline" },
            variant: "emphasis",
          },
        },
        {
          type: "contact",
          id: "contacto",
          content: {
            heading: "Pide tu presupuesto sin compromiso",
            subheading: "Cuéntanos tu proyecto y te responderemos a la mayor brevedad.",
            details: [
              { label: "Teléfono", value: business.telephone!, href: PHONE_HREF },
              { label: "Email", value: business.email!, href: `mailto:${business.email}` },
              { label: "Zona de trabajo", value: "Valencia y área metropolitana" },
            ],
            form: {
              submitLabel: "Enviar solicitud",
              fields: [
                { name: "nombre", label: "Nombre", required: true },
                { name: "telefono", label: "Teléfono", type: "tel", required: true },
                { name: "email", label: "Email", type: "email", required: true },
                {
                  name: "tipo-reforma",
                  label: "Tipo de reforma",
                  type: "select",
                  required: true,
                  options: [
                    { label: "Reforma integral", value: "integral" },
                    { label: "Cocina", value: "cocina" },
                    { label: "Baño", value: "bano" },
                    { label: "Pintura", value: "pintura" },
                    { label: "Electricidad y fontanería", value: "electricidad-fontaneria" },
                    { label: "Otro", value: "otro" },
                  ],
                },
                {
                  name: "presupuesto",
                  label: "Presupuesto aproximado",
                  type: "select",
                  options: [
                    { label: "Menos de 5.000 €", value: "lt-5000" },
                    { label: "5.000 € - 15.000 €", value: "5000-15000" },
                    { label: "15.000 € - 30.000 €", value: "15000-30000" },
                    { label: "Más de 30.000 €", value: "gt-30000" },
                    { label: "Aún no lo sé", value: "unsure" },
                  ],
                },
                {
                  name: "mensaje",
                  label: "Cuéntanos tu proyecto",
                  type: "textarea",
                  required: true,
                  placeholder: "Describe brevemente qué te gustaría reformar...",
                },
                {
                  name: "imagenes",
                  label: "Adjuntar imágenes (opcional)",
                  type: "file",
                  accept: "image/*",
                  multiple: true,
                },
              ],
            },
          },
        },
      ],
    },
  ],
};

export const NAV_LINKS = [
  { label: "Inicio", href: "#inicio" },
  { label: "Servicios", href: "#servicios" },
  { label: "Proyectos", href: "#proyectos" },
  { label: "Proceso", href: "#proceso" },
  { label: "Opiniones", href: "#opiniones" },
  { label: "Contacto", href: "#contacto" },
] as const;

export const HEADER_CTA = { label: "Pedir presupuesto", href: "#contacto" } as const;

export const CONTACT_INFO = {
  phoneDisplay: business.telephone!,
  phoneHref: PHONE_HREF,
  email: business.email!,
};
