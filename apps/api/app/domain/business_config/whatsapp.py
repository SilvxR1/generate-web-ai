"""WhatsAppConfig — a business's opt-in WhatsApp contact channel (P1.1).

Deliberately simple: this is a high-conversion contact CTA (a `wa.me`
deep link with an optional prefilled message), not WhatsApp Business API
automation — no conversational bot, no credentials, no webhook. Reuses
BusinessProfile.contact's phone-validation shape (`_validate_phone_like`)
rather than inventing a second phone format. `enabled` defaults False and
`phone_number` has no default: a business is never rendered as having
WhatsApp available just because this config object exists — see
BusinessConfig's `_whatsapp_requires_phone_number` validator, which
refuses `enabled=True` without a real number rather than silently
downgrading it.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.business_config.business_profile import _validate_phone_like


class WhatsAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # E.164-ish, same tolerant format BusinessProfile.contact.whatsapp
    # already accepts (spaces/dashes/parens allowed, normalized to digits
    # only at link-generation time — see the website generator's
    # toWhatsAppHref). No default: a phone number is never fabricated.
    phone_number: str | None = None
    # Never a claim the business hasn't made itself (e.g. no invented
    # response-time promise) — this is genuinely optional prefilled text,
    # shown to the visitor before they send it.
    default_message: str | None = Field(default=None, max_length=300)
    show_floating_button: bool = False
    show_contact_cta: bool = False
    # Gates whether a whatsapp_click analytics event may fire at all for
    # this business — independent of whether visitor consent actually
    # grants ANALYTICS (app.domain.enums.ConsentCategory), which is
    # always checked client-side regardless of this flag.
    tracking_enabled: bool = True

    @field_validator("phone_number")
    @classmethod
    def _validate_phone_number(cls, value: str | None) -> str | None:
        return _validate_phone_like(value) if value else value
