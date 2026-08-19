// Entry point for the content blocks package. Composable, business-agnostic
// page sections built from @generate-web-ai/ui. Each block takes a single
// typed `content` prop; a client site supplies content, not new UI code.

export { default as Hero } from "./components/Hero.astro";
export { default as Services } from "./components/Services.astro";
export { default as Features } from "./components/Features.astro";
export { default as Testimonials } from "./components/Testimonials.astro";
export { default as FAQ } from "./components/FAQ.astro";
export { default as CTA } from "./components/CTA.astro";
export { default as Contact } from "./components/Contact.astro";

export type { HeroContent } from "./components/Hero.astro";
export type { ServicesContent, ServiceItem } from "./components/Services.astro";
export type { FeaturesContent, FeatureItem } from "./components/Features.astro";
export type { TestimonialsContent, TestimonialItem } from "./components/Testimonials.astro";
export type { FAQContent, FAQItem } from "./components/FAQ.astro";
export type { CTAContent } from "./components/CTA.astro";
export type {
  ContactContent,
  ContactDetail,
  ContactForm,
  ContactFormField,
} from "./components/Contact.astro";

export type { BlockAction, BlockImage } from "./types";
