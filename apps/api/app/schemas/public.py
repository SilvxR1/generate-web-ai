"""Request/response shapes for app.routers.public — the one deliberately
anonymous surface in this API (Phase 7). Deliberately separate from
app.schemas.lead: those types describe an *authenticated* view of an
already-persisted Lead; these describe untrusted input from an anonymous
website visitor, which needs its own validation rules (honeypot, timing,
no tenant_id field to smuggle) that would never belong on the internal
shape.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

MAX_LEAD_DETAILS = 12


class PublicLeadDetail(BaseModel):
    """One additional form field (H1.2). `key` is a stable identifier the
    site chose, `label` what the visitor saw, `value` what they entered."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)


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

    # H1.2: the site form's own additional fields (e.g. requested service,
    # surface area) — structured, bounded and labelled as the visitor saw
    # them, so nothing the form asks is lost or squeezed into `message`.
    details: list[PublicLeadDetail] = Field(default_factory=list, max_length=MAX_LEAD_DETAILS)
    # H1.2: a client-generated id per submission attempt series. A retry
    # after a network error reuses it; the endpoint stores at most one
    # lead per (business, submission_id) and answers retries identically.
    submission_id: UUID | None = None

    @model_validator(mode="after")
    def _at_least_one_contact_method(self) -> "PublicLeadCreateRequest":
        if not self.email and not self.phone:
            raise ValueError("Provide at least an email or a phone number.")
        keys = [detail.key for detail in self.details]
        if len(keys) != len(set(keys)):
            raise ValueError("Each form detail key may appear only once.")
        return self


class PublicLeadCreateResponse(BaseModel):
    """Deliberately minimal — never echoes back the created Lead's id or
    any other internal detail (Phase 7: "safe error responses"), and
    identical whether or not the submission was actually stored (a
    silently-dropped spam submission still gets this same response — see
    app.routers.public's own docstring)."""

    model_config = ConfigDict(extra="forbid")

    received: bool = True
