import type { SiteConfig } from "./site-config.ts";

/**
 * A minimal, valid SiteConfig exercising every current block type. Used by
 * the renderer's example page and its validation script to prove a
 * multi-block config renders correctly end to end.
 */
export const exampleSiteConfig: SiteConfig = {
  brand: {
    name: "Riverside Plumbing Co.",
    tagline: "Reliable plumbing, day or night.",
  },
  theme: {
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
  },
  features: {
    contactForm: true,
    chatbot: false,
    booking: false,
  },
  pages: [
    {
      path: "/",
      blocks: [
        {
          type: "hero",
          id: "hero",
          content: {
            eyebrow: "Locally owned",
            heading: "Reliable plumbing, day or night",
            subheading: "Licensed, insured, and on call across the metro area.",
            primaryAction: { label: "Book a visit", href: "/contact" },
            secondaryAction: { label: "Our services", href: "#services" },
          },
        },
        {
          type: "services",
          id: "services",
          content: {
            heading: "What we do",
            items: [
              { title: "Leak repair", description: "Fast fixes for leaks big and small." },
              { title: "Drain cleaning", description: "Clear clogs without the mess." },
              { title: "Water heaters", description: "Installation, repair, and replacement." },
            ],
          },
        },
        {
          type: "features",
          content: {
            heading: "Why choose us",
            items: [
              { title: "24/7 emergency line", description: "Real people, day or night." },
              { title: "Upfront pricing", description: "No surprises on the invoice." },
            ],
          },
        },
        {
          type: "testimonials",
          content: {
            heading: "What customers say",
            items: [{ quote: "Fixed our leak in under an hour.", author: "Dana M.", rating: 5 }],
          },
        },
        {
          type: "faq",
          content: {
            heading: "Frequently asked questions",
            items: [{ question: "Do you offer emergency service?", answer: "Yes, 24/7." }],
          },
        },
        {
          type: "cta",
          content: {
            heading: "Ready when you are",
            primaryAction: { label: "Call now", href: "tel:+15555550123" },
          },
        },
        {
          type: "contact",
          id: "contact",
          content: {
            heading: "Get in touch",
            details: [{ label: "Phone", value: "(555) 555-0123", href: "tel:+15555550123" }],
            form: {
              fields: [
                { name: "name", label: "Name", required: true },
                { name: "message", label: "Message", type: "textarea", required: true },
              ],
            },
          },
        },
      ],
    },
  ],
};
