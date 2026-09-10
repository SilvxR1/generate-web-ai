"""Request/response shapes for app.routers.public — the one deliberately
anonymous surface in this API (Phase 7). Deliberately separate from
app.schemas.lead: those types describe an *authenticated* view of an
already-persisted Lead; these describe untrusted input from an anonymous
website visitor, which needs its own validation rules (honeypot, timing,
no tenant_id field to smuggle) that would never belong on the internal
shape.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class PublicLeadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    message: str | None = Field(default=None, max_length=5000)
    subject: str | None = Field(default=None, max_length=200)
    # The page this form was actually submitted from — preserved as
    # provenance (Phase 7), never trusted for anything else.
    source_url: str | None = Field(default=None, max_length=2048)
    # A real consent checkbox on the public form — recorded verbatim,
    # never defaulted to true.
    consent: bool = False

    # --- Spam boundary (Phase 8) — never validated/rejected here, only
    # carried through to app.leads.spam.is_spam, so a bot that trips
    # either check gets an ordinary-looking success response rather than
    # a rule to learn from.

    # A field the real form renders visually hidden (CSS, not
    # type="hidden" — some bots skip that) — a real visitor never fills
    # it in.
    company_website: str = Field(default="", max_length=200)
    # When the form was rendered, set client-side on page load (ISO
    # 8601). A submission arriving faster than a human could plausibly
    # type is treated as spam.
    rendered_at: datetime | None = None

    @model_validator(mode="after")
    def _at_least_one_contact_method(self) -> "PublicLeadCreateRequest":
        if not self.email and not self.phone:
            raise ValueError("Provide at least an email or a phone number.")
        return self


class PublicLeadCreateResponse(BaseModel):
    """Deliberately minimal — never echoes back the created Lead's id or
    any other internal detail (Phase 7: "safe error responses"), and
    identical whether or not the submission was actually stored (a
    silently-dropped spam submission still gets this same response — see
    app.routers.public's own docstring)."""

    model_config = ConfigDict(extra="forbid")

    received: bool = True
