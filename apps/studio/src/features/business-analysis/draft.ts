import type { BusinessConfig, BusinessVertical, LeadSource } from "@generate-web-ai/business-config-types";
import type { AnalyzeBusinessResponse, CreateBusinessPayload } from "../../lib/api";

/** Client-side mirror of apps/api's BusinessProfile.slug SLUG_PATTERN
 * (app.domain.business_config.business_profile) — kept in sync by hand,
 * same as this package's other generated-but-not-validated types. */
export const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function slugify(text: string): string {
  const withoutAccents = text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  const collapsed = withoutAccents
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return collapsed.slice(0, 100).replace(/-+$/, "");
}

export const BUSINESS_VERTICAL_OPTIONS: Array<{ value: BusinessVertical; label: string }> = [
  { value: "home_renovation", label: "Home renovation" },
  { value: "real_estate", label: "Real estate" },
  { value: "clinic", label: "Clinic / healthcare" },
  { value: "agency", label: "Agency" },
  { value: "b2b_services", label: "B2B services" },
  { value: "restaurant", label: "Restaurant" },
  { value: "ecommerce", label: "E-commerce" },
  { value: "hotel", label: "Hotel" },
  { value: "other", label: "Other" },
];

export const LEAD_SOURCE_OPTIONS: Array<{ value: LeadSource; label: string }> = [
  { value: "website_form", label: "Website form" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "whatsapp", label: "WhatsApp" },
  { value: "manual", label: "Manual entry" },
  { value: "other", label: "Other" },
];

export interface ServiceDraft {
  /** React list identity only — never sent to the backend. The real
   * ServiceOffering.id is derived from `name` at submit time. */
  key: string;
  name: string;
  description: string;
  category: string;
}

let serviceDraftCounter = 0;
export function nextServiceDraftKey(): string {
  serviceDraftCounter += 1;
  return `service-draft-${serviceDraftCounter}`;
}

export interface AutomationDraft {
  leadCapture: boolean;
  leadNotifications: boolean;
  customerAcknowledgement: boolean;
  followUpEnabled: boolean;
  /** Hours, 1–720 (see validateDraft) — the field the generator
   * actually consumes (AutomationConfig.follow_up.delay_hours). Not
   * the free-form `delay` string BusinessConfig also carries: that one
   * is never read by anything, so this draft doesn't expose it. */
  followUpDelayHours: number;
}

export interface BusinessDraft {
  name: string;
  slug: string;
  /** Once the operator edits the slug directly, stop auto-deriving it
   * from `name` edits. */
  slugTouched: boolean;
  vertical: BusinessVertical;
  rawDescription: string;
  description: string;
  targetCustomers: string;
  location: { city: string; region: string; country: string; postalCode: string };
  services: ServiceDraft[];
  contact: { email: string; phone: string; whatsapp: string; website: string };
  leadSources: LeadSource[];
  automation: AutomationDraft;
}

/** Builds the editable working copy from the AI's proposal — every
 * field a human can then correct before anything is saved. `null`
 * sub-objects on the proposal (BusinessConfig fields the analyzer left
 * unset) become empty strings/lists here, never a guessed value. */
export function buildDraftFromAnalysis(response: AnalyzeBusinessResponse, briefing: string): BusinessDraft {
  const profile = response.proposed_config?.business_profile;
  const name = profile?.name ?? "";

  return {
    name,
    slug: profile?.slug ?? (name ? slugify(name) : ""),
    slugTouched: Boolean(profile?.slug),
    vertical: profile?.industry ?? "other",
    rawDescription: briefing,
    description: profile?.description ?? "",
    targetCustomers: profile?.target_customers ?? "",
    location: {
      city: profile?.location?.city ?? "",
      region: profile?.location?.region ?? "",
      country: profile?.location?.country ?? "",
      postalCode: profile?.location?.postal_code ?? "",
    },
    services: (profile?.services ?? []).map((service) => ({
      key: nextServiceDraftKey(),
      name: service.name,
      description: service.description,
      category: service.category ?? "",
    })),
    contact: {
      email: profile?.contact?.email ?? "",
      phone: profile?.contact?.phone ?? "",
      whatsapp: profile?.contact?.whatsapp ?? "",
      website: profile?.contact?.website ?? "",
    },
    leadSources: response.proposed_config?.lead_management?.sources ?? [],
    automation: {
      leadCapture: response.proposed_config?.automation?.lead_capture ?? false,
      leadNotifications: response.proposed_config?.automation?.lead_notifications ?? false,
      customerAcknowledgement: response.proposed_config?.automation?.customer_acknowledgement ?? false,
      followUpEnabled: response.proposed_config?.automation?.follow_up?.enabled ?? false,
      // 24 matches AutomationConfig.follow_up's own default (apps/api's
      // Pydantic model) — a proposal that doesn't set delay_hours
      // (e.g. it only set the free-form `delay` string) still gets a
      // sane, non-zero starting value here.
      followUpDelayHours: response.proposed_config?.automation?.follow_up?.delay_hours ?? 24,
    },
  };
}

/** Client-side gate before ever calling POST /businesses — catches an
 * "invalid proposal" (blank name, malformed slug, half-filled location)
 * without a round trip. The backend still validates everything again;
 * this only saves an obviously-doomed request. */
export function validateDraft(draft: BusinessDraft): string[] {
  const errors: string[] = [];

  if (!draft.name.trim()) {
    errors.push("Business name is required.");
  }
  if (!SLUG_PATTERN.test(draft.slug.trim())) {
    errors.push('Slug must be lowercase letters, numbers, and single hyphens only (e.g. "my-business").');
  }
  if (draft.rawDescription.trim().length < 10) {
    errors.push("Description must be at least 10 characters.");
  }

  const city = draft.location.city.trim();
  const country = draft.location.country.trim();
  if ((city || country) && !(city && country)) {
    errors.push("Location needs both a city and a country code, or leave both empty.");
  }
  if (country && country.length !== 2) {
    errors.push("Country must be a 2-letter code (e.g. ES, US).");
  }

  if (draft.contact.email.trim() && !draft.contact.email.includes("@")) {
    errors.push("Contact email doesn't look valid.");
  }

  if (draft.automation.followUpEnabled) {
    const hours = draft.automation.followUpDelayHours;
    if (!Number.isInteger(hours) || hours < 1 || hours > 720) {
      errors.push("Follow-up delay must be a whole number of hours between 1 and 720.");
    }
  }

  draft.services.forEach((service, index) => {
    const hasName = service.name.trim().length > 0;
    const hasDescription = service.description.trim().length > 0;
    if (hasName !== hasDescription) {
      errors.push(`Service #${index + 1} needs both a name and a description, or leave both empty.`);
    }
  });

  return errors;
}

/** Converts the reviewed draft into the exact POST /businesses body.
 * Only called after validateDraft(draft) is empty. */
export function buildCreatePayload(draft: BusinessDraft): CreateBusinessPayload {
  const name = draft.name.trim();
  const hasLocation = draft.location.city.trim().length > 0 && draft.location.country.trim().length > 0;
  const hasContact = [draft.contact.email, draft.contact.phone, draft.contact.whatsapp, draft.contact.website].some(
    (value) => value.trim().length > 0,
  );

  const seenServiceIds = new Set<string>();
  const services = draft.services
    .filter((service) => service.name.trim() && service.description.trim())
    .map((service, index) => {
      const base = slugify(service.name) || `service-${index + 1}`;
      let id = base;
      let suffix = 2;
      while (seenServiceIds.has(id)) {
        id = `${base}-${suffix}`;
        suffix += 1;
      }
      seenServiceIds.add(id);
      return {
        id,
        name: service.name.trim(),
        description: service.description.trim(),
        category: service.category.trim() || undefined,
      };
    });

  const config: BusinessConfig = {
    schema_version: 1,
    business_profile: {
      name,
      slug: draft.slug.trim(),
      industry: draft.vertical,
      description: draft.description.trim() || undefined,
      location: hasLocation
        ? {
            city: draft.location.city.trim(),
            region: draft.location.region.trim() || undefined,
            country: draft.location.country.trim().toUpperCase(),
            postal_code: draft.location.postalCode.trim() || undefined,
          }
        : undefined,
      services,
      target_customers: draft.targetCustomers.trim() || undefined,
      contact: hasContact
        ? {
            email: draft.contact.email.trim() || undefined,
            phone: draft.contact.phone.trim() || undefined,
            whatsapp: draft.contact.whatsapp.trim() || undefined,
            website: draft.contact.website.trim() || undefined,
          }
        : undefined,
    },
    lead_management: {
      enabled: draft.leadSources.length > 0,
      sources: draft.leadSources,
    },
    automation: {
      lead_capture: draft.automation.leadCapture,
      lead_notifications: draft.automation.leadNotifications,
      customer_acknowledgement: draft.automation.customerAcknowledgement,
      follow_up: {
        enabled: draft.automation.followUpEnabled,
        // Omitted (not sent as a bogus value) when follow-up is off —
        // the backend's own default (24) applies, which doesn't matter
        // since nothing reads it while disabled anyway.
        delay_hours: draft.automation.followUpEnabled ? draft.automation.followUpDelayHours : undefined,
      },
    },
    // Without this, apps/api's app.notifications.service silently never
    // delivers either email (CommunicationConfig.internal_notifications/
    // customer_notifications.email both default to false) even with the
    // matching automation checkbox on — the two checkboxes above enable
    // *generating* the workflow step, this enables the one channel that
    // actually exists (email) to *deliver* it. No new field: both are
    // already-modeled BusinessConfig.communications toggles, just never
    // previously set from here.
    communications: {
      internal_notifications: { email: draft.automation.leadNotifications },
      customer_notifications: { email: draft.automation.customerAcknowledgement },
    },
  };

  return {
    name,
    slug: draft.slug.trim(),
    vertical: draft.vertical,
    raw_description: draft.rawDescription.trim().slice(0, 5000),
    status: "draft",
    config,
  };
}
