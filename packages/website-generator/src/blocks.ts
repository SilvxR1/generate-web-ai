import type {
  BusinessProfile,
  LeadManagementConfig,
} from "@generate-web-ai/business-config-types";
import type {
  ContactBlockConfig,
  ContactDetailConfig,
  ContactFormConfig,
  ContactFormFieldConfig,
  CTABlockConfig,
  FeaturesBlockConfig,
  HeroBlockConfig,
  ServicesBlockConfig,
} from "@generate-web-ai/site-config";
import type { WebsiteGeneratorPreset } from "./presets.ts";

function toTelHref(phone: string): string {
  return `tel:${phone.replace(/[\s()-]/g, "")}`;
}

function toWhatsAppHref(whatsapp: string): string {
  return `https://wa.me/${whatsapp.replace(/\D/g, "")}`;
}

/**
 * Hero: name and (real) location only. Deliberately never sets `stat`
 * (HeroBlockContent.stat) — that field exists specifically for a claim
 * like "+10 años de experiencia", exactly the kind of unverifiable
 * business fact this generator must never invent.
 */
export function buildHeroBlock(profile: BusinessProfile, preset: WebsiteGeneratorPreset): HeroBlockConfig {
  const services = profile.services ?? [];

  return {
    type: "hero",
    id: "hero",
    content: {
      ...(profile.location?.city ? { eyebrow: profile.location.city } : {}),
      heading: profile.name,
      subheading: profile.description || preset.heroSubheadingFallback || undefined,
      primaryAction: { label: "Contactar", href: "#contact" },
      ...(services.length > 0 ? { secondaryAction: { label: "Ver servicios", href: "#services" } } : {}),
    },
  };
}

/** Only generated when there's at least one real service — no
 * placeholder services. */
export function buildServicesBlock(profile: BusinessProfile, preset: WebsiteGeneratorPreset): ServicesBlockConfig | null {
  const services = profile.services ?? [];
  if (services.length === 0) return null;

  return {
    type: "services",
    id: "services",
    content: {
      heading: preset.servicesHeading,
      items: services.map((service) => ({
        title: service.name,
        description: service.short_description || service.description,
        featured: service.featured,
      })),
    },
  };
}

/**
 * "About" reuses the `features` block type — packages/site-config has no
 * dedicated "about" block, and adding one would be exactly the
 * duplicated/parallel website-schema this generator must not create.
 * `features` is the closest existing block that fits (heading +
 * subheading + title/description items), and every item here traces to
 * a real BusinessProfile field: service_area and target_customers. Both
 * absent -> no block (no invented "why choose us" content).
 */
export function buildAboutBlock(profile: BusinessProfile, preset: WebsiteGeneratorPreset): FeaturesBlockConfig | null {
  const items: FeaturesBlockConfig["content"]["items"] = [];
  const serviceArea = profile.service_area ?? [];

  if (serviceArea.length > 0) {
    items.push({ title: "Zona de servicio", description: serviceArea.join(", ") });
  }
  if (profile.target_customers) {
    items.push({ title: "¿Para quién?", description: profile.target_customers });
  }

  if (items.length === 0 && !profile.description) return null;

  return {
    type: "features",
    id: "about",
    content: {
      heading: preset.aboutHeading,
      ...(profile.description ? { subheading: profile.description } : {}),
      items,
    },
  };
}

/** Always generated — every business has *something* worth a
 * call-to-action, and both fields here are generic template copy plus a
 * real in-page anchor, never a claim about the business. */
export function buildCtaBlock(profile: BusinessProfile, preset: WebsiteGeneratorPreset): CTABlockConfig {
  const phone = profile.contact?.phone;

  return {
    type: "cta",
    id: "cta",
    content: {
      heading: preset.ctaHeading,
      primaryAction: { label: preset.ctaPrimaryLabel, href: "#contact" },
      ...(phone ? { secondaryAction: { label: "Llamar ahora", href: toTelHref(phone) } } : {}),
    },
  };
}

const FORM_FIELD_BUILDERS: Record<string, (profile: BusinessProfile) => ContactFormFieldConfig> = {
  name: () => ({ name: "name", label: "Nombre", type: "text", required: true }),
  email: () => ({ name: "email", label: "Email", type: "email", required: true }),
  phone: () => ({ name: "phone", label: "Teléfono", type: "tel", required: true }),
  message: () => ({ name: "message", label: "Mensaje", type: "textarea", required: true }),
  service: (profile) => ({
    name: "service",
    label: "Servicio",
    type: "select",
    required: true,
    options: (profile.services ?? []).map((service) => ({ label: service.name, value: service.id })),
  }),
};

/**
 * Builds the lead-capture form purely from LeadManagementConfig.required_fields
 * — the "LeadForm" the brief asks for, realized as the `contact` block's
 * existing `form` field (packages/site-config already models this;
 * adding a separate "leadform" block type would duplicate it). `action`
 * is deliberately left unset: Contact.astro's submit handler treats a
 * form with no `action` as not-yet-wired-to-a-backend and dispatches a
 * neutral `lead.submitted` DOM event instead of posting anywhere — no
 * n8n/CRM connection, per this phase's explicit scope.
 */
function buildLeadForm(profile: BusinessProfile, leadManagement: LeadManagementConfig, preset: WebsiteGeneratorPreset): ContactFormConfig {
  const fields = (leadManagement.required_fields ?? []).map((fieldName) => {
    const build = FORM_FIELD_BUILDERS[fieldName];
    if (!build) {
      throw new Error(
        `Unknown lead_management.required_fields entry ${JSON.stringify(fieldName)}. ` +
          `Known fields: ${Object.keys(FORM_FIELD_BUILDERS).join(", ")}.`,
      );
    }
    return build(profile);
  });

  return { fields, submitLabel: preset.formSubmitLabel };
}

function buildContactDetails(profile: BusinessProfile): ContactDetailConfig[] {
  const details: ContactDetailConfig[] = [];
  const { contact } = profile;
  if (!contact) return details;

  if (contact.phone) details.push({ label: "Teléfono", value: contact.phone, href: toTelHref(contact.phone) });
  if (contact.email) details.push({ label: "Email", value: contact.email, href: `mailto:${contact.email}` });
  if (contact.whatsapp) details.push({ label: "WhatsApp", value: contact.whatsapp, href: toWhatsAppHref(contact.whatsapp) });
  if (contact.address) {
    const { street_address, locality, region, postal_code } = contact.address;
    const value = [street_address, locality, region, postal_code].filter(Boolean).join(", ");
    details.push({ label: "Dirección", value });
  }

  return details;
}

/** Only generated when there's at least a real contact detail or a
 * real lead-capture form to show — never an empty shell. */
export function buildContactBlock(
  profile: BusinessProfile,
  leadManagement: LeadManagementConfig | undefined,
  preset: WebsiteGeneratorPreset,
): ContactBlockConfig | null {
  const details = buildContactDetails(profile);
  const wantsForm = Boolean(leadManagement?.enabled && (leadManagement.sources ?? []).includes("website_form"));
  const form = wantsForm && leadManagement ? buildLeadForm(profile, leadManagement, preset) : undefined;

  if (details.length === 0 && !form) return null;

  return {
    type: "contact",
    id: "contact",
    content: {
      heading: preset.contactHeading,
      ...(details.length > 0 ? { details } : {}),
      ...(form ? { form } : {}),
    },
  };
}
