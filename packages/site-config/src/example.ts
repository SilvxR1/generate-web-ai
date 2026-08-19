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
  seo: {
    title: "Riverside Plumbing Co. | Reliable plumbing, day or night",
    description: "Licensed, insured plumbing repair, drain cleaning, and water heater service across the metro area.",
    ogImage: { src: "/images/og-default.jpg", alt: "Riverside Plumbing Co. van outside a home" },
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
      seo: {
        title: "Riverside Plumbing Co. | Home",
        description: "24/7 emergency plumbing, drain cleaning, and water heater service in the metro area.",
      },
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
              {
                title: "Leak repair",
                description: "Fast fixes for leaks big and small.",
                image: { src: "/images/services/leak-repair.jpg", alt: "Plumber repairing a pipe under a sink" },
              },
              { title: "Drain cleaning", description: "Clear clogs without the mess." },
              { title: "Water heaters", description: "Installation, repair, and replacement." },
            ],
          },
        },
        {
          type: "process",
          id: "process",
          content: {
            heading: "How it works",
            subheading: "From first call to finished repair.",
            steps: [
              { title: "Call or book online", description: "Tell us what's going on and when works for you." },
              { title: "We diagnose the issue", description: "A licensed plumber inspects and quotes the fix." },
              { title: "We do the work", description: "Repairs are completed with upfront, agreed pricing." },
              { title: "Follow-up guarantee", description: "Every repair is backed by our workmanship guarantee." },
            ],
          },
        },
        {
          type: "gallery",
          id: "gallery",
          content: {
            heading: "Recent jobs",
            items: [
              {
                title: "Kitchen pipe replacement",
                category: "Repair",
                image: { src: "/images/gallery/kitchen-pipe.jpg", alt: "Replaced copper piping under a kitchen sink" },
                description: "Full repipe after a slow leak damaged the cabinet base.",
                link: { label: "See the details", href: "#contact" },
              },
              {
                title: "Water heater upgrade",
                category: "Installation",
                image: { src: "/images/gallery/water-heater.jpg", alt: "New tankless water heater installed on a wall" },
                beforeAfter: {
                  before: { src: "/images/gallery/water-heater-before.jpg", alt: "Old tank water heater before removal" },
                  after: { src: "/images/gallery/water-heater-after.jpg", alt: "New tankless water heater after installation" },
                },
              },
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
                { name: "email", label: "Email", type: "email", required: true },
                {
                  name: "service",
                  label: "What do you need help with?",
                  type: "select",
                  required: true,
                  options: [
                    { label: "Leak repair", value: "leak-repair" },
                    { label: "Drain cleaning", value: "drain-cleaning" },
                    { label: "Water heater", value: "water-heater" },
                    { label: "Something else", value: "other" },
                  ],
                },
                {
                  name: "urgency",
                  label: "How urgent is this?",
                  type: "radio",
                  required: true,
                  options: [
                    { label: "Emergency (today)", value: "emergency" },
                    { label: "This week", value: "this-week" },
                    { label: "Just planning ahead", value: "planning" },
                  ],
                },
                {
                  name: "photos",
                  label: "Photos of the issue (optional)",
                  type: "file",
                  accept: "image/*",
                  multiple: true,
                },
                {
                  name: "consent",
                  label: "Consent",
                  type: "checkbox",
                  placeholder: "I agree to be contacted about this request.",
                  required: true,
                },
                { name: "message", label: "Message", type: "textarea", required: true },
              ],
            },
          },
        },
      ],
    },
  ],
};
