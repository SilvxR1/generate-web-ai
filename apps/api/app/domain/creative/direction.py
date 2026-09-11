"""CreativeDirection — the P2 domain concept between a CreativeBrief
(facts) and a concrete implementation: what a CreativeDirectorProvider
(app.creative.director) proposes a business's website should *feel* like,
not which prebuilt template/block/variant to use.

Deliberately vocabulary, not selection: every field here is free-text
description of intent (narrative, mood, composition philosophy,
navigation concept, ...), never an enum of predefined UI options like
`heroVariant`/`galleryVariant`/`designFamily`. An AI Frontend Engineer
(app.creative.frontend_engine) interprets this creatively; nothing in
this module or its callers reduces a CreativeDirection back down to a
finite template choice. See docs/architecture.md's "Creative Orchestrator"
section and this module's own field docstrings for why each block exists.

Every factual claim a generated site is allowed to make still comes from
BusinessConfig/CreativeBrief, never from here — `constraints` on this
model is the explicit allow/forbid boundary a CreativeDirection carries
forward to the frontend engine (P2.9's factual-safety layer), not a place
new facts are invented.
"""

from pydantic import BaseModel, ConfigDict, Field


class CreativeConcept(BaseModel):
    """The core creative idea in a few sentences — what makes this
    direction distinct from another candidate, and why it fits this
    specific business (never a generic "modern and clean" description
    that could apply to any business)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rationale: str
    narrative: str


class VisualLanguage(BaseModel):
    """Art direction as description, not as picked values — `mood`/
    `palette_direction`/`typography_direction` are prose ("warm,
    handmade, sun-bleached terracotta and cream, imperfect hand-drawn
    accents"), never a hex code or a font-family name a template system
    would select from a fixed list. `graphic_language` covers iconography/
    illustration/texture/pattern language distinct from photography
    treatment itself (`imagery_treatment`)."""

    model_config = ConfigDict(extra="forbid")

    mood: str
    palette_direction: str
    typography_direction: str
    composition_philosophy: str
    imagery_treatment: str
    graphic_language: str


class ExperienceDirection(BaseModel):
    """How a visitor moves through and interacts with the site — never a
    fixed `navigationModel` enum. `interaction_concepts`/
    `motion_concepts` are lists of described behaviors ("cards tilt
    toward the cursor", "sections reveal via a circular iris transition
    on route change"), for the frontend engine to implement however fits
    its actual component structure."""

    model_config = ConfigDict(extra="forbid")

    navigation_concept: str
    storytelling_model: str
    interaction_concepts: list[str] = Field(default_factory=list)
    motion_concepts: list[str] = Field(default_factory=list)
    responsive_adaptation: str


class ContentStrategy(BaseModel):
    """What the site is *for*, structurally — `hierarchy` describes what
    matters most and why (not a fixed section order list the way
    packages/website-generator's block ordering already is for the
    deterministic engine), `primary_user_journey` the intended path from
    arrival to conversion, `conversion_strategy` how the direction itself
    (not just a CTA block) is meant to drive that conversion."""

    model_config = ConfigDict(extra="forbid")

    hierarchy: str
    primary_user_journey: str
    conversion_strategy: str


class CreativeDirectionConstraints(BaseModel):
    """The factual-safety boundary a CreativeDirection carries forward
    into frontend generation (P2.9) — never a place new facts originate.
    `factual_claims` are copied verbatim from CreativeBrief/BusinessConfig
    (real, already-known facts safe to state); `allowed_claims` are
    categories of safe generic language (e.g. "custom orders",
    "handmade") that don't require a specific number/date/certification;
    `prohibited_claims` names the specific fabrication categories P2.9
    lists (pricing, years of experience, certifications, reviews,
    guarantees, addresses, hours, shipping, delivery times, materials,
    customer counts, awards, availability, ecommerce) that aren't backed
    by BusinessConfig for this business; `required_content` is what must
    appear regardless of creative interpretation (e.g. a working contact
    path, legal page links)."""

    model_config = ConfigDict(extra="forbid")

    factual_claims: list[str] = Field(default_factory=list)
    allowed_claims: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    required_content: list[str] = Field(default_factory=list)


class CreativeDirection(BaseModel):
    """One candidate (or the selected, deepened) creative direction for a
    business's website — the structured output of
    CreativeDirectorProvider.create_directions/develop_direction
    (app.creative.director). Persisted via
    app.db.models.creative_direction.CreativeDirection (the ORM row);
    this is the pure domain shape, no SQLAlchemy/FastAPI dependency,
    mirroring CreativeBrief's own boundary.

    `is_recommended`/`selection_rationale` are set by the critic
    (app.creative.critic.select_direction) after all candidates from one
    create_directions call exist — never by the provider itself, which
    proposes candidates but never judges between them (same "explore" vs.
    "select" separation as CreativeOrchestrator.select_provider being
    separate from any CreativeProvider implementation).
    """

    model_config = ConfigDict(extra="forbid")

    concept: CreativeConcept
    visual_language: VisualLanguage
    experience: ExperienceDirection
    content_strategy: ContentStrategy
    # URLs/descriptions of reference material this direction is grounded
    # in — a Higgsfield-generated moodboard/reference image, a real
    # business photo it was built around, or (for the internal fallback
    # director) empty, since no reference material exists without a
    # premium provider.
    references: list[str] = Field(default_factory=list)
    constraints: CreativeDirectionConstraints = Field(default_factory=CreativeDirectionConstraints)

    # Which provider produced this (CreativeProviderName.value) plus
    # whatever that provider wants to record about the call (job id,
    # model used, prompt template — never a credential). Opaque to every
    # caller except the provider that wrote it, same convention as
    # CreativeGenerationResult.raw_metadata.
    provider_metadata: dict = Field(default_factory=dict)
    # When/how this candidate was produced — deliberately separate from
    # provider_metadata (which is provider-specific content) so a caller
    # can always find generation_metadata["credits_used"]/
    # ["duration_ms"]/["stage"] (e.g. "initial_direction" vs "developed")
    # without knowing which provider produced this row.
    generation_metadata: dict = Field(default_factory=dict)

    is_recommended: bool = False
    selection_rationale: str | None = None
