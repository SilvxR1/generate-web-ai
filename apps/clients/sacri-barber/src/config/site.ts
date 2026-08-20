// Sacri Barber — SiteConfig. This file is the single source of truth for
// the client's brand, theme, and page content: PageRenderer (from
// @generate-web-ai/renderer) turns `siteConfig.pages` into rendered blocks,
// and Layout.astro applies `siteConfig.theme`/`siteConfig.brand` to the
// page shell. Nothing about Sacri Barber is hardcoded into markup outside
// this file and the app shell (Header/Footer/Layout).
import type { AssetConfig, LocalBusinessConfig, SiteConfig } from "@generate-web-ai/site-config";

import heroImg from "../assets/hero/barberia-interior.jpg";
import servicioCorteClasicoImg from "../assets/services/corte-clasico.jpg";
import servicioCorteBarbaImg from "../assets/services/corte-barba.jpg";
import servicioAfeitadoImg from "../assets/services/afeitado-navaja.jpg";
import servicioArregloBarbaImg from "../assets/services/arreglo-barba.jpg";
import servicioDisenoBarbaImg from "../assets/services/diseno-barba.jpg";
import servicioColoracionImg from "../assets/services/coloracion.jpg";
import fadeClasicoImg from "../assets/gallery/fade-clasico.jpg";
import acabadoSecadorImg from "../assets/gallery/acabado-secador.jpg";
import barbaAntesImg from "../assets/gallery/barba-antes.jpg";
import barbaDespuesImg from "../assets/gallery/barba-despues.jpg";
import sillonSesionImg from "../assets/gallery/sillon-sesion.jpg";
import rinconVintageImg from "../assets/gallery/rincon-vintage.jpg";

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
 * content (an invented Madrid address and a typical barbershop schedule) —
 * see src/assets/IMAGE-SOURCES.md for the same disclosure already made
 * about the gallery/testimonials content. This is the single source for
 * both the on-page contact details below and the schema.org `LocalBusiness`
 * JSON-LD emitted from `Layout.astro`.
 */
const business: LocalBusinessConfig = {
  telephone: "+34 910 00 00 00",
  email: "hola@sacribarber.example",
  address: {
    streetAddress: "Calle del Pez, 21",
    addressLocality: "Madrid",
    addressRegion: "Madrid",
    postalCode: "28004",
    addressCountry: "ES",
  },
  openingHours: [{ dayOfWeek: ["Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"], opens: "10:00", closes: "20:00" }],
  priceRange: "€",
};

const PHONE_HREF = `tel:${business.telephone!.replace(/\s+/g, "")}`;

export const siteConfig: SiteConfig = {
  brand: {
    name: "Sacri Barber",
    tagline: "Barbería clásica en Malasaña, Madrid",
  },
  theme: {
    colors: {
      // Kept equal to `foreground`, matching the convention already
      // established in reforma-casa-valencia's Layout.astro: `--ui-*`
      // generation there only reads secondary/accent/background/foreground
      // directly, so `primary` isn't independently load-bearing today.
      primary: "#F3E9D2",
      secondary: "#3A322A",
      accent: "#D4AF37",
      background: "#16130F",
      foreground: "#F3E9D2",
    },
    fonts: {
      sans: "'Inter', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
      display: "'Oswald', 'Arial Narrow', sans-serif",
    },
    radius: {
      base: "0.25rem",
      lg: "0.5rem",
    },
  },
  business,
  features: {
    contactForm: true,
    chatbot: false,
    booking: false,
  },
  seo: {
    title: "Sacri Barber | Barbería clásica en Malasaña, Madrid",
    description:
      "Barbería en Malasaña, Madrid: corte clásico, barba y afeitado a navaja con precios claros. Reserva tu cita hoy mismo.",
    ogImage: asset(heroImg, "Interior de barbería clásica con sillón de cuero y pared de ladrillo visto"),
  },
  pages: [
    {
      path: "/",
      seo: {
        title: "Sacri Barber — Corte, barba y afeitado clásico en Malasaña, Madrid",
        description:
          "Corte clásico, combinado con barba y afeitado a navaja en Malasaña, Madrid. Precios orientativos claros y un espacio con carácter.",
        ogImage: asset(heroImg, "Interior de barbería clásica con sillón de cuero y pared de ladrillo visto"),
      },
      blocks: [
        {
          type: "hero",
          id: "inicio",
          content: {
            eyebrow: "Barbería en Malasaña, Madrid",
            heading: "El oficio del barbero, sin prisas.",
            subheading:
              "Corte, barba y afeitado a navaja en un espacio con carácter. Nos tomamos el tiempo que tu imagen merece.",
            primaryAction: { label: "Reservar cita", href: "#reservar" },
            secondaryAction: { label: "Ver servicios", href: "#servicios", variant: "outline" },
            image: asset(heroImg, "Sillón de barbero de cuero negro frente a una pared de ladrillo visto, con luces cálidas"),
            stat: { value: "+8", label: "años cortando el pelo en Malasaña" },
          },
        },
        {
          type: "services",
          id: "servicios",
          content: {
            heading: "Servicios y precios",
            subheading: "Precios orientativos — te confirmamos el presupuesto exacto en la propia barbería.",
            items: [
              {
                title: "Corte clásico — 15 €",
                description: "Corte a tijera y máquina, lavado incluido y acabado con toalla caliente.",
                image: asset(servicioCorteClasicoImg, "Barbero cortando el pelo a un cliente con tijera"),
                action: { label: "Reservar cita", href: "#reservar" },
                featured: true,
              },
              {
                title: "Corte + barba — 25 €",
                description: "El combo completo: corte de pelo y arreglo de barba en la misma sesión.",
                image: asset(servicioCorteBarbaImg, "Barbero usando tijera de entresacar cerca de la oreja de un cliente"),
                action: { label: "Reservar cita", href: "#reservar" },
              },
              {
                title: "Afeitado a navaja — 18 €",
                description: "Afeitado tradicional con navaja, toallas calientes y productos de barbería clásica.",
                image: asset(servicioAfeitadoImg, "Barbero afeitando con navaja tradicional"),
                action: { label: "Reservar cita", href: "#reservar" },
              },
              {
                title: "Arreglo de barba — 12 €",
                description: "Perfilado y recorte de barba para mantener la forma día a día.",
                image: asset(servicioArregloBarbaImg, "Recorte de barba con tijera, fotografía en blanco y negro"),
                action: { label: "Reservar cita", href: "#reservar" },
              },
              {
                title: "Diseño de barba — 15 €",
                description: "Diseño a medida de la línea de barba, con detalle a navaja en los bordes.",
                image: asset(servicioDisenoBarbaImg, "Primer plano de una barba bien definida y cuidada"),
                action: { label: "Reservar cita", href: "#reservar" },
              },
              {
                title: "Coloración y cuidado — 20 €",
                description: "Cobertura de canas y tratamientos de cuidado con productos profesionales.",
                image: asset(servicioColoracionImg, "Herramientas y productos de barbería sobre una superficie de pizarra"),
                action: { label: "Reservar cita", href: "#reservar" },
              },
            ],
          },
        },
        {
          type: "gallery",
          id: "galeria",
          background: "surface",
          content: {
            heading: "Trabajos en la barbería",
            subheading:
              "Una muestra de nuestro estilo de trabajo. Fotos ilustrativas creadas para esta demostración, no corresponden a clientes reales.",
            items: [
              {
                title: "Fade clásico",
                category: "Cortes",
                image: asset(fadeClasicoImg, "Barbero con camisa blanca cortando un degradado clásico"),
                description: "Degradado limpio con textura arriba, acabado de barbería tradicional.",
                link: { label: "Ver detalles", href: "#contacto" },
                featured: true,
              },
              {
                title: "Últimos retoques",
                category: "Cortes",
                image: asset(acabadoSecadorImg, "Barbero terminando un peinado con secador"),
                description: "El acabado final: peinado y secado antes de salir por la puerta.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
              {
                title: "Un antes y un después",
                category: "Barba",
                image: asset(barbaDespuesImg, "Retrato de cliente con la barba arreglada, sonriendo"),
                description: "Dos momentos de la barbería: así dejamos la barba lista para salir.",
                beforeAfter: {
                  before: asset(barbaAntesImg, "Retrato de perfil de cliente con barba larga, antes de la sesión"),
                  after: asset(barbaDespuesImg, "Retrato de cliente con la barba arreglada, después de la sesión"),
                  beforeLabel: "Antes",
                  afterLabel: "Después",
                },
              },
              {
                title: "Un momento en el sillón",
                category: "Barbería",
                image: asset(sillonSesionImg, "Cliente sentado en un sillón de barbero durante una sesión"),
                description: "El ritual de cada cita: tiempo, cuidado y buena conversación.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
              {
                title: "Rincón vintage de la barbería",
                category: "Barbería",
                image: asset(rinconVintageImg, "Fila de sillones de barbero vintage con acabados dorados"),
                description: "El espacio donde pasa la magia: sillones, espejos y herramientas de toda la vida.",
                link: { label: "Ver detalles", href: "#contacto" },
              },
            ],
          },
        },
        {
          type: "testimonials",
          id: "opiniones",
          content: {
            heading: "Lo que dicen nuestros clientes",
            subheading: "Opiniones de ejemplo, creadas para esta demostración.",
            items: [
              {
                quote:
                  "Vengo desde hace años y el trato es siempre igual de bueno. Saben exactamente cómo quiero el corte sin tener que explicarlo.",
                author: "Marcos Vidal",
                role: "Malasaña, Madrid",
                rating: 5,
                featured: true,
              },
              {
                quote: "El afeitado a navaja es una pasada. Ambiente clásico y muy buen rollo.",
                author: "Diego Herrera",
                role: "Chamberí, Madrid",
                rating: 5,
              },
              {
                quote: "Llevo a mi hijo desde que tenía 6 años, ahora tiene 14 y seguimos viniendo. Un clásico del barrio.",
                author: "Rubén Castillo",
                role: "Malasaña, Madrid",
                rating: 5,
              },
            ],
          },
        },
        {
          type: "contact",
          id: "contacto",
          background: "surface",
          content: {
            heading: "Reserva tu cita",
            subheading: "Pásate por la barbería o escríbenos y te confirmamos hueco.",
            details: [
              { label: "Teléfono", value: business.telephone!, href: PHONE_HREF },
              { label: "Email", value: business.email!, href: `mailto:${business.email}` },
              { label: "Dirección", value: "Calle del Pez, 21, 28004 Madrid" },
              { label: "Horario", value: "Martes a sábado, 10:00 - 20:00" },
            ],
            form: {
              submitLabel: "Reservar cita",
              fields: [
                { name: "nombre", label: "Nombre", required: true },
                { name: "telefono", label: "Teléfono", type: "tel", required: true },
                { name: "email", label: "Email", type: "email", required: true },
                {
                  name: "servicio",
                  label: "Servicio",
                  type: "select",
                  required: true,
                  options: [
                    { label: "Corte clásico", value: "corte-clasico" },
                    { label: "Corte + barba", value: "corte-barba" },
                    { label: "Afeitado a navaja", value: "afeitado-navaja" },
                    { label: "Arreglo de barba", value: "arreglo-barba" },
                    { label: "Diseño de barba", value: "diseno-barba" },
                    { label: "Coloración y cuidado", value: "coloracion" },
                    { label: "Otro", value: "otro" },
                  ],
                },
                {
                  name: "mensaje",
                  label: "Cuéntanos qué día y hora prefieres",
                  type: "textarea",
                  placeholder: "Ej: martes o miércoles por la tarde...",
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
  { label: "Galería", href: "#galeria" },
  { label: "Opiniones", href: "#opiniones" },
  { label: "Contacto", href: "#contacto" },
  { label: "Reservar", href: "#reservar" },
] as const;

export const HEADER_CTA = { label: "Reservar cita", href: "#reservar" } as const;

export const CONTACT_INFO = {
  phoneDisplay: business.telephone!,
  phoneHref: PHONE_HREF,
  email: business.email!,
};
