/* eslint-disable */
/**
 * Generated from apps/api's BusinessConfig (Pydantic) via
 * apps/api/scripts/export_business_config_contract.py +
 * packages/business-config-types/scripts/generate-types.mjs.
 * Do not hand-edit — the Python model is the source of truth.
 */

/**
 * Used by BusinessProfile's business_hours (app.domain.business_config)
 * — a controlled vocabulary in place of packages/site-config's
 * LocalBusinessOpeningHours.dayOfWeek, which is free-text on the
 * TypeScript side (schema.org's DayOfWeek values) because that layer is
 * trusted, hand-authored content. This layer isn't.
 */
export type Weekday = "monday" | "tuesday" | "wednesday" | "thursday" | "friday" | "saturday" | "sunday";
/**
 * Extensible on purpose (Section 4 of the master context: don't
 * hardcode the product to the reformas vertical). New verticals are added
 * here as they're validated with real clients; OTHER is the escape hatch
 * until then.
 */
export type BusinessVertical =
  | "home_renovation"
  | "real_estate"
  | "clinic"
  | "agency"
  | "b2b_services"
  | "restaurant"
  | "ecommerce"
  | "hotel"
  | "other";
/**
 * MVP scope only (Section 9's stated priority order). Extend as later
 * providers are added — Outlook, Teams, Drive, Notion, Salesforce,
 * WhatsApp, Telegram.
 */
export type IntegrationProvider = "webhook" | "gmail" | "google_sheets" | "slack" | "hubspot";
/**
 * Where a lead can come from — Section 8's stated initial set.
 */
export type LeadSource = "website_form" | "email" | "phone" | "whatsapp" | "manual" | "other";

export interface BusinessConfig {
  automation?: AutomationConfig;
  brand?: BrandConfig | null;
  business_profile: BusinessProfile;
  communications?: CommunicationConfig;
  creative?: CreativeConfig;
  integrations?: IntegrationPreferences;
  lead_management?: LeadManagementConfig;
  legal_profile?: LegalProfile | null;
  schema_version?: number;
  website?: WebsiteConfig;
  whatsapp?: WhatsAppConfig;
}
export interface AutomationConfig {
  customer_acknowledgement?: boolean;
  enabled_features?: string[];
  follow_up?: FollowUpConfig;
  lead_capture?: boolean;
  lead_notifications?: boolean;
}
export interface FollowUpConfig {
  delay?: string | null;
  delay_hours?: number;
  enabled?: boolean;
}
export interface BrandConfig {
  assets?: AssetRef[];
  colors: BrandColors;
  logo?: AssetRef | null;
  tagline?: string | null;
  typography: BrandTypography;
  visual_style?: string | null;
}
/**
 * A referenced image (logo, brand asset). `url` is a plain string —
 * not a strict URL type — because nothing generates or validates real
 * asset URLs yet (no upload pipeline exists); over-constraining this
 * before that exists would just make the schema harder to fill in for
 * no real benefit. `alt` is required so nothing built from this is
 * inaccessible by construction, matching AssetConfig's own rule in
 * packages/site-config.
 */
export interface AssetRef {
  alt: string;
  url: string;
}
/**
 * Mirrors ThemeColorConfig exactly. Deliberately not restricted to
 * hex-only — Tailwind v4 (this repo's styling layer) accepts named
 * colors, rgb()/hsl()/oklch(), etc., and the TypeScript type this
 * mirrors never restricted the format either.
 */
export interface BrandColors {
  accent: string;
  background: string;
  foreground: string;
  primary: string;
  secondary: string;
}
/**
 * Mirrors ThemeFontConfig: `sans` required, `display` optional
 * (falls back to `sans` when omitted, same as the TypeScript side).
 */
export interface BrandTypography {
  display?: string | null;
  sans: string;
}
/**
 * The core "who is this business" facts. Only name/slug/industry are
 * required — everything else can be filled in incrementally (Section 3:
 * not every field has to be mandatory).
 */
export interface BusinessProfile {
  business_hours?: BusinessHoursRule[];
  contact?: ContactInfo | null;
  description?: string | null;
  industry: BusinessVertical;
  location?: Location | null;
  name: string;
  service_area?: string[];
  services?: ServiceOffering[];
  slug: string;
  target_customers?: string | null;
}
/**
 * One opening-hours rule: a set of days sharing the same opening and
 * closing time. Mirrors packages/site-config's
 * LocalBusinessOpeningHours shape, but `days` is a controlled
 * vocabulary (Weekday) rather than free-text — this layer isn't
 * trusted hand-authored content the way that one is.
 */
export interface BusinessHoursRule {
  closes: string;
  /**
   * @minItems 1
   */
  days: [Weekday, ...Weekday[]];
  opens: string;
}
/**
 * How customers reach the business. Every field optional — Section 4
 * warns against restrictions that would make real businesses (e.g. one
 * with only a phone, no email) unrepresentable.
 */
export interface ContactInfo {
  address?: PostalAddress | null;
  email?: string | null;
  phone?: string | null;
  website?: string | null;
  whatsapp?: string | null;
}
/**
 * Mirrors packages/site-config's LocalBusinessAddress field-for-field
 * (streetAddress/addressLocality/addressRegion/postalCode/
 * addressCountry) so this data stays compatible with that package's
 * schema.org LocalBusiness JSON-LD shape if a future website generator
 * needs to emit it from BusinessConfig instead of hand-authored config.
 */
export interface PostalAddress {
  country: string;
  locality: string;
  postal_code?: string | null;
  region?: string | null;
  street_address: string;
}
/**
 * Coarse operating location for service-area context — not
 * necessarily a full mailing address (see ContactInfo.address for
 * that). Deliberately shallow per Section 3's instruction not to
 * over-model geography.
 */
export interface Location {
  city: string;
  country: string;
  postal_code?: string | null;
  region?: string | null;
}
/**
 * A service the business offers, at the business-catalog level —
 * price/category, not rendering props. Deliberately NOT the same type
 * as packages/site-config's ServiceItemConfig (icon/image/action/
 * featured, meant for a Services block's rendering), which sits one
 * abstraction level lower: that's what a website generator would
 * eventually produce FROM a ServiceOffering, not a shape this layer
 * should hold directly.
 */
export interface ServiceOffering {
  category?: string | null;
  description: string;
  featured?: boolean;
  id: string;
  name: string;
  price_from?: number | null;
  price_unit?: string | null;
  short_description?: string | null;
}
export interface CommunicationConfig {
  customer_notifications?: NotificationPreferences;
  email_enabled?: boolean;
  internal_notifications?: NotificationPreferences;
  phone_enabled?: boolean;
  whatsapp_enabled?: boolean;
}
/**
 * Channel toggles only. Never: smtp_password, slack_token, api_key,
 * or any other credential — those belong to Credential
 * (app.db.models.credential), a different bounded context.
 */
export interface NotificationPreferences {
  email?: boolean;
  slack?: boolean;
  whatsapp?: boolean;
}
export interface CreativeConfig {
  /**
   * How premium a creative generation request is — what
   * CreativeOrchestrator.select_provider (app.creative.orchestrator) uses
   * to route between InternalCreativeProvider and a premium provider like
   * Higgsfield. No pricing is encoded here (Section 12: "do not hardcode
   * pricing yet") — this is purely a capability/routing signal.
   */
  level?: "basic" | "professional" | "premium" | "cinematic";
  preferred_provider?: string | null;
  /**
   * How much of a business's existing visual identity a creative
   * generation request should preserve versus reimagine. A typed domain
   * concept per the Creative Orchestrator brief (Section 5) rather than
   * an arbitrary string scattered across CreativeConfig/CreativeBrief/
   * CreativeProvider — every layer that branches on strategy branches on
   * one of exactly these three values.
   */
  strategy?: "preserve" | "evolve" | "new_direction";
}
export interface IntegrationPreferences {
  crm?: IntegrationProvider | null;
  email?: IntegrationProvider | null;
  internal_notifications?: IntegrationProvider | null;
  spreadsheets?: IntegrationProvider | null;
}
export interface LeadManagementConfig {
  acknowledgement?: boolean;
  destination?: IntegrationProvider | null;
  enabled?: boolean;
  follow_up?: boolean;
  required_fields?: string[];
  sources?: LeadSource[];
}
export interface LegalProfile {
  address?: PostalAddress | null;
  data_processors?: string[];
  legal_name?: string | null;
  privacy_contact_email?: string | null;
  registration_number?: string | null;
  tax_id?: string | null;
}
export interface WebsiteConfig {
  enabled?: boolean;
  seo?: SEOPreferences | null;
  template_preference?: string | null;
}
/**
 * Mirrors packages/site-config's SEOConfig (title/description/
 * ogImage) — the site-wide default a generator would carry over.
 */
export interface SEOPreferences {
  description?: string | null;
  og_image?: AssetRef | null;
  title?: string | null;
}
export interface WhatsAppConfig {
  default_message?: string | null;
  enabled?: boolean;
  phone_number?: string | null;
  show_contact_cta?: boolean;
  show_floating_button?: boolean;
  tracking_enabled?: boolean;
}
