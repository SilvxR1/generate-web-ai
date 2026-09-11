"""BusinessAnalysisOutput — the exact JSON shape a BusinessAnalyzer
provider must return via constrained structured output (never free-text
parsing). Provider-agnostic: any LLM capable of schema-constrained JSON
output can target this shape, which is why it lives here rather than
under app.analysis.claude alongside the Claude-specific client.

Every field is optional. That is the whole point: the model must never
invent a value it wasn't given, so omission — not a guess — is the
correct response to missing information. app.analysis.assembly turns
this (always-optional, never-trusted-as-final) shape into an actual,
schema-validated BusinessConfig, filling in only what BusinessConfig
itself already defaults.

Deliberately smaller than a full mirror of BusinessConfig: Anthropic's
structured-output ("messages.parse") call rejects a schema this rich
once it also carries brand preferences, communication-channel
preferences, and the full automation-intentions object, failing with
"The compiled grammar is too large" / "Schema is too complex" — a
provider-side limit on the whole schema's combined complexity, not a
defect in any single field. Brand/communication-channel preferences and
the finer automation intents (customer acknowledgement, follow-up) are
dropped from what the analyzer extracts; a human still sets all of
those in the review step (ProposalReview), same as before — only the
*automated* proposal for them is gone, not the BusinessConfig
capability itself. `automation_lead_capture`/`automation_lead_notifications`
stay as flat booleans (not a nested object) because that's exactly what
kept the schema under the provider's limit in testing.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import BusinessVertical, LeadSource


class RawLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str | None = None
    region: str | None = None
    # Only ever filled in when the model is confident of the ISO 3166-1
    # alpha-2 code — left null otherwise, never guessed (BusinessProfile's
    # Location requires exactly 2 characters; assembly.py treats a bad
    # value as "ask the human", not as a hard failure).
    country: str | None = None
    postal_code: str | None = None


class RawServiceOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    category: str | None = None


class RawContactInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    website: str | None = None


class BusinessAnalysisOutput(BaseModel):
    """The literal `output_format` passed to the LLM provider's
    structured-output call. `missing_information`/`questions` are the
    model's own account of what it couldn't determine — assembly.py
    treats them as untrusted analysis content to carry forward, same as
    every other field here, never as instructions."""

    model_config = ConfigDict(extra="forbid")

    business_name: str | None = None
    industry: BusinessVertical | None = None
    # Customer-facing: this flows, largely verbatim (see
    # packages/website-generator's copy.ts `sanitizeCustomerCopy` for the
    # deterministic safety net), into published hero/about copy and the
    # SEO meta description — never internal briefing/strategy commentary
    # about the website project itself (LR-08). See prompts.py's
    # SYSTEM_PROMPT rule 6 for the instruction this field's extraction
    # actually follows.
    description: str | None = None
    location: RawLocation | None = None
    services: list[RawServiceOffering] = Field(default_factory=list)
    target_customers: str | None = None
    contact: RawContactInfo | None = None
    lead_sources: list[LeadSource] = Field(default_factory=list)
    automation_lead_capture: bool | None = None
    automation_lead_notifications: bool | None = None
    missing_information: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
