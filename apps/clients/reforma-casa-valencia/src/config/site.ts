// ReformaCasa Valencia — SiteConfig.
//
//   BusinessConfig (business.ts)  +  home_renovation preset (website-generator)
//        ↓ generateSiteConfig()
//   brand / theme / business (JSON-LD) / features / seo / services block
//        +  client overrides below
//        ↓
//   siteConfig  →  PageRenderer  →  rendered site
//
// Split: brand, theme, the schema.org `business` facts, `features`, the
// site-level `seo`, and the Services block all come straight from
// generateSiteConfig(businessConfig) — nothing hand-duplicated. Every
// other block below is an explicit override because it genuinely can't
// be derived from BusinessConfig yet: real photography (no image field
// exists on BusinessConfig), hand-written marketing copy, and the
// gallery/testimonials/FAQ/process sections, which are demo content for
// a fictitious client (see IMAGE-SOURCES.md) — content the generator
// must never invent on its own, but that a human can write and disclose
// as an override. The one deliberate content change from the previous,
// fully hand-written version: the hero's "+10 años de experiencia" stat
// and the matching bullet in "Por qué elegirnos" are removed — an
// unverified years-of-experience claim is exactly what
// generateSiteConfig() refuses to invent, and keeping it only in the
// hand-written override would undercut that rule for no real reason.
import type { AssetConfig, ServicesBlockConfig, SiteConfig } from "@generate-web-ai/site-config";
import { generateSiteConfig } from "@generate-web-ai/website-generator";
import { businessConfig } from "./business";

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
 * unoptimized `<img>`. Per-item service/project photography like this has
 * no equivalent field on BusinessConfig yet (ServiceOffering deliberately
 * excludes imagery — see apps/api's business_profile.py) — another reason
 * the blocks using it below stay overrides rather than generated.
 */
function asset(image: ImageMetadata, alt: string): AssetConfig {
  return { src: image, alt };
}

const generated = generateSiteConfig(businessConfig);

const servicesBlock = generated.pages[0]?.blocks.find(
  (block): block is ServicesBlockConfig => block.type === "services",
);
if (!servicesBlock) {
  throw new Error("generateSiteConfig(businessConfig) did not produce a services block — check business.ts.");
}

const PHONE_HREF = `tel:${businessConfig.business_profile.contact!.phone!.replace(/\s+/g, "")}`;

export const siteConfig: SiteConfig = {
  brand: generated.brand,
  theme: generated.theme,
  business: generated.business,
  features: generated.features,
  seo: generated.seo,
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
        // --- override: real photo + hand-written marketing headline ---
        {
          type: "hero",
          id: "inicio",
          content: {
            heading: "Transformamos espacios para vivirlos mejor.",
            subheading:
              "Reformas integrales y parciales en Valencia, con un equipo que cuida cada detalle desde la primera visita hasta la entrega final.",
            primaryAction: { label: "Pedir presupuesto", href: "#contacto" },
            secondaryAction: { label: "Ver proyectos", href: "#proyectos", variant: "outline" },
            image: asset(heroImg, "Salón de estilo mediterráneo con chimenea de piedra, vigas de madera y luz natural cálida"),
          },
        },
        // --- override: value props a human vouches for, not automated claims ---
        {
          type: "features",
          id: "por-que-elegirnos",
          background: "surface",
          content: {
            heading: "Por qué elegir ReformaCasa Valencia",
            subheading: "Un equipo local que acompaña tu reforma de principio a fin.",
            items: [
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
        // --- generated: content from businessConfig.business_profile.services ---
        {
          ...servicesBlock,
          id: "servicios",
          content: {
            ...servicesBlock.content,
            subheading: "Reformas integrales y por especialidad, adaptadas a cada vivienda.",
            items: servicesBlock.content.items.map((item, index) => {
              const images = [
                servicioIntegralImg,
                servicioCocinasImg,
                servicioBanosImg,
                servicioPinturaImg,
                servicioInstalacionesImg,
                servicioDisenoImg,
              ];
              return {
                ...item,
                image: asset(images[index]!, item.title),
                action: { label: "Pedir presupuesto", href: "#contacto" },
              };
            }),
          },
        },
        // --- override: not a BusinessConfig concept ---
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
        // --- override: demo content, explicitly disclosed as fictitious below ---
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
        // --- override: demo content, explicitly disclosed as fictitious below ---
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
        // --- override: client-specific Q&A ---
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
        // --- override: richer copy + phone action than the generic preset CTA ---
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
        // --- override: richer form (budget range, reform type, image upload) than
        // generateSiteConfig's LeadManagementConfig.required_fields can express yet ---
        {
          type: "contact",
          id: "contacto",
          content: {
            heading: "Pide tu presupuesto sin compromiso",
            subheading: "Cuéntanos tu proyecto y te responderemos a la mayor brevedad.",
            details: [
              { label: "Teléfono", value: businessConfig.business_profile.contact!.phone!, href: PHONE_HREF },
              { label: "Email", value: businessConfig.business_profile.contact!.email!, href: `mailto:${businessConfig.business_profile.contact!.email}` },
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
  phoneDisplay: businessConfig.business_profile.contact!.phone!,
  phoneHref: PHONE_HREF,
  email: businessConfig.business_profile.contact!.email!,
};
