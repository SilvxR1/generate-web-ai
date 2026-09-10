"""LegalProfile — the real, human-provided facts about the legal entity
operating a business, used to fill in the generated website's legal
pages (Privacy Policy, Terms of Service, Cookie Policy — see
packages/website-generator's legal.ts) and nothing else. Every field is
optional and this codebase never fabricates a value for one that's
missing: P0's explicit constraint is "Do NOT fabricate: company
registration numbers, addresses, legal names, tax IDs, third-party
processors. Missing required information should be surfaced as
incomplete, not invented." Consumers (Studio's legal-profile form, the
generated legal pages themselves) show an explicit "not provided"
placeholder for any empty field rather than guessing or omitting the
field's row entirely — the gap itself is the useful signal.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.business_config.business_profile import PostalAddress


class LegalProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The entity's registered legal name — may differ from
    # BusinessProfile.name (a trading/brand name), which is why this
    # isn't just reused from there.
    legal_name: str | None = Field(default=None, max_length=200)
    registration_number: str | None = Field(default=None, max_length=100)
    tax_id: str | None = Field(default=None, max_length=100)
    address: PostalAddress | None = None
    privacy_contact_email: EmailStr | None = None
    # Real third-party processors this business actually uses (e.g.
    # "Resend (transactional email)", "Cloudflare (hosting)") — always
    # human-entered. This codebase never infers or auto-populates this
    # list itself, since doing so would assert a data-processing
    # relationship this app cannot actually verify.
    data_processors: list[str] = Field(default_factory=list)
