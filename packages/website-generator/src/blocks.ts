import type {
  BusinessProfile,
  LeadManagementConfig,
  WhatsAppConfig as BusinessWhatsAppConfig,
} from "@generate-web-ai/business-config-types";
import type {
  ContactBlockConfig,
  ContactDetailConfig,
  ContactFormConfig,
  ContactFormFieldConfig,
  ContactWhatsAppCtaConfig,
  CTABlockConfig,
  FeaturesBlockConfig,
  GalleryBlockConfig,
  HeroBlockConfig,
  ServicesBlockConfig,
  WhatsAppConfig,
} from "@generate-web-ai/site-config";
import type { BusinessAssetInput } from "./assets.ts";
import { assetToImageConfig } from "./assets.ts";
import type { WebsiteGeneratorPreset } from "./presets.ts";

function toTelHref(phone: string): string {
  return `tel:${phone.replace(/[\s()-]/g, "")}`;
}

/** `message` is prefilled text the visitor sees in the WhatsApp compose
 * box before sending — never invented here, always exactly whatever the
 * caller passed (a real BusinessConfig.whatsapp.default_message, or
 * none). */
function toWhatsAppHref(whatsapp: string, message?: string): string {
  const digits = whatsapp.replace(/\D/g, "");
  return message ? `https://wa.me/${digits}?text=${encodeURIComponent(message)}` : `https://wa.me/${digits}`;
}

/**
 * BusinessConfig.whatsapp (Python-mirrored, snake_case) ->
 * site-config's WhatsAppConfig (camelCase) — the same kind of field-
 * rename bridge buildSeo/buildBusiness already do elsewhere in this
 * package. Returns undefined for every "nothing to render" state
 * (config absent, disabled, or enabled with no real phone number — the
 * last of which BusinessConfig's own validator already refuses to
 * persist, but this stays defensive rather than assuming that always
 * held true upstream) so callers never need a second enabled-check.
 */
export function buildWhatsAppConfig(whatsappConfig: BusinessWhatsAppConfig | undefined): WhatsAppConfig | undefined {
  if (!whatsappConfig?.enabled || !whatsappConfig.phone_number) return undefined;

  return {
    enabled: true,
    phoneNumber: whatsappConfig.phone_number,
    ...(whatsappConfig.default_message ? { defaultMessage: whatsappConfig.default_message } : {}),
    showFloatingButton: Boolean(whatsappConfig.show_floating_button),
    showContactCta: Boolean(whatsappConfig.show_contact_cta),
    trackingEnabled: whatsappConfig.tracking_enabled !== false,
  };
}

/**
 * Hero: name and (real) location only. Deliberately never sets `stat`
 * (HeroBlockContent.stat) — that field exists specifically for a claim
 * like "+10 años de experiencia", exactly the kind of unverifiable
 * business fact this generator must never invent.
 *
 * `subheading` is selected existing customer-facing text only: the real
 * tagline or one whole sentence of the sanitized description (copy.ts'
 * `selectHeroSupportingCopy`, LR-08, A8.3.2). The full description lives
 * in About, so the hero never repeats it. `heroImage` is a real BusinessAsset chosen by the caller
 * (assets.ts's `selectHeroAsset`) — never a generated/stock substitute
 * while a real photo exists (LR-05).
 *
 * `hasContactSection` is whether the page will actually contain the
 * `contact` block — the "#contact" action is only emitted when it will,
 * so every in-page anchor always resolves to a rendered id (the same
 * invariant app.qa.platform_contract's broken_anchor_target enforces).
 */
export function buildHeroBlock(
  profile: BusinessProfile,
  preset: WebsiteGeneratorPreset,
  heroSupportingCopy: string | undefined,
  heroImage?: BusinessAssetInput,
  hasContactSection = true,
  hasDescription = heroSupportingCopy !== undefined,
): HeroBlockConfig {
  const services = profile.services ?? [];

  return {
    type: "hero",
    id: "hero",
    content: {
      ...(profile.location?.city ? { eyebrow: profile.location.city } : {}),
      heading: profile.name,
      // A8.3.2: `heroSupportingCopy` is a tagline or a single whole sentence
      // chosen by copy.ts' selectHeroSupportingCopy; never the full
      // description (that belongs to About). The preset line is kept only
      // for a business with no usable description at all.
      subheading: heroSupportingCopy ?? (hasDescription ? undefined : preset.heroSubheadingFallback || undefined),
      ...(hasContactSection ? { primaryAction: { label: "Contactar", href: "#contact" } } : {}),
      ...(services.length > 0 ? { secondaryAction: { label: "Ver servicios", href: "#services" } } : {}),
      ...(heroImage ? { image: assetToImageConfig(heroImage, `Foto de ${profile.name}`) } : {}),
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
export function buildAboutBlock(
  profile: BusinessProfile,
  preset: WebsiteGeneratorPreset,
  customerFacingDescription: string | undefined,
  // A8.3.2: false when the hero already shows this exact text, so the same
  // paragraph is never shown twice. The text still appears once, in the hero.
  includeDescription = true,
): FeaturesBlockConfig | null {
  const items: FeaturesBlockConfig["content"]["items"] = [];
  const serviceArea = profile.service_area ?? [];

  if (serviceArea.length > 0) {
    items.push({ title: "Zona de servicio", description: serviceArea.join(", ") });
  }
  if (profile.target_customers) {
    items.push({ title: "¿Para quién?", description: profile.target_customers });
  }

  const description = includeDescription ? customerFacingDescription : undefined;
  if (items.length === 0 && !description) return null;

  return {
    type: "features",
    id: "about",
    content: {
      heading: preset.aboutHeading,
      ...(description ? { subheading: description } : {}),
      items,
    },
  };
}

/** Only generated when the business has real gallery-worthy photography
 * (assets.ts's `selectGalleryAssets`), never placeholder imagery.
 *
 * A8.3.2: item text is shown only when it adds information.
 * - No title is manufactured. The asset model has no per-photo title or
 *   caption, and a category label ("Trabajo realizado") is not the photo's
 *   title, so `title` is omitted.
 * - The category badge is real, owner-classified metadata, but it is shown
 *   only when the displayed photos span at least two categories. There it
 *   actually distinguishes items; a single repeated label adds nothing.
 * - Alt text is unchanged: the real `alt_text`, otherwise the deterministic
 *   "{business} — foto N" fallback. Nothing is inferred from the image or
 *   its filename. */
const CATEGORY_LABELS: Record<string, string> = {
  project: "Proyecto",
  gallery: "Trabajo realizado",
  product: "Producto",
  before: "Antes",
  after: "Después",
  team: "Equipo",
  facility: "Instalaciones",
};

export function buildGalleryBlock(
  images: readonly BusinessAssetInput[],
  preset: WebsiteGeneratorPreset,
  businessName: string,
): GalleryBlockConfig | null {
  if (images.length === 0) return null;

  const distinctCategories = new Set(images.map((asset) => asset.category));
  const showCategory = distinctCategories.size >= 2;

  return {
    type: "gallery",
    id: "gallery",
    content: {
      heading: preset.galleryHeading,
      items: images.map((asset, index) => {
        const category = CATEGORY_LABELS[asset.category];
        return {
          ...(showCategory && category ? { category } : {}),
          image: assetToImageConfig(asset, `${businessName} — foto ${index + 1}`),
        };
      }),
    },
  };
}

/** Generated whenever the page has a `contact` block to point at (the
 * caller decides — its primary action is always the in-page "#contact"
 * anchor, so without that section it would be a dead link). Both fields
 * here are generic template copy plus that real in-page anchor, never a
 * claim about the business. */
export function buildCtaBlock(
  profile: BusinessProfile,
  preset: WebsiteGeneratorPreset,
  variant: "default" | "emphasis" = "default",
): CTABlockConfig {
  const phone = profile.contact?.phone;

  return {
    type: "cta",
    id: "cta",
    content: {
      heading: preset.ctaHeading,
      primaryAction: { label: preset.ctaPrimaryLabel, href: "#contact" },
      ...(phone ? { secondaryAction: { label: "Llamar ahora", href: toTelHref(phone) } } : {}),
      ...(variant !== "default" ? { variant } : {}),
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

/** Only present when WhatsAppConfig.show_contact_cta is explicitly set —
 * P1.1's "do NOT force all three [placements]; configuration should
 * decide" applies here as much as to the floating button. */
function buildContactWhatsAppCta(whatsappConfig: BusinessWhatsAppConfig | undefined): ContactWhatsAppCtaConfig | undefined {
  if (!whatsappConfig?.enabled || !whatsappConfig.show_contact_cta || !whatsappConfig.phone_number) return undefined;
  return {
    href: toWhatsAppHref(whatsappConfig.phone_number, whatsappConfig.default_message ?? undefined),
    label: "Hablar por WhatsApp",
  };
}

/** Only generated when there's at least a real contact detail, a real
 * lead-capture form, or a WhatsApp CTA to show — never an empty shell. */
export function buildContactBlock(
  profile: BusinessProfile,
  leadManagement: LeadManagementConfig | undefined,
  preset: WebsiteGeneratorPreset,
  whatsappConfig?: BusinessWhatsAppConfig,
): ContactBlockConfig | null {
  const details = buildContactDetails(profile);
  const wantsForm = Boolean(leadManagement?.enabled && (leadManagement.sources ?? []).includes("website_form"));
  const form = wantsForm && leadManagement ? buildLeadForm(profile, leadManagement, preset) : undefined;
  const whatsappCta = buildContactWhatsAppCta(whatsappConfig);

  if (details.length === 0 && !form && !whatsappCta) return null;

  return {
    type: "contact",
    id: "contact",
    content: {
      heading: preset.contactHeading,
      ...(details.length > 0 ? { details } : {}),
      ...(form ? { form } : {}),
      ...(whatsappCta ? { whatsappCta } : {}),
    },
  };
}
