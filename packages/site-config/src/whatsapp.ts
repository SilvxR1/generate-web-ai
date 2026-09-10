/**
 * WhatsAppConfig — a business's opt-in WhatsApp contact channel (P1.1).
 * High-conversion CTAs (a `wa.me` deep link, optionally prefilled) only —
 * no WhatsApp Business API automation, no conversational bot. Mirrors
 * `@generate-web-ai/business-config-types`' WhatsAppConfig field-for-field
 * (the Python BusinessConfig.whatsapp this is generated from); kept as an
 * independent declaration for the same reason every other site-config
 * type is (see blocks.ts's file header) — this package has no dependency
 * on the Python-generated types.
 */
export interface WhatsAppConfig {
  enabled: boolean;
  /** E.164-ish digits/spaces/dashes, already validated upstream. */
  phoneNumber: string;
  defaultMessage?: string;
  showFloatingButton?: boolean;
  showContactCta?: boolean;
  /** Gates whether a `whatsapp_click` analytics event may fire at all —
   * independent of whether visitor consent actually grants ANALYTICS,
   * which is always checked client-side regardless of this flag. */
  trackingEnabled?: boolean;
}
