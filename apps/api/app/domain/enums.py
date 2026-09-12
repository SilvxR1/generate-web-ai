"""Domain vocabulary shared by the database models (app.db.models) and the
Pydantic schemas (app.schemas). Defined once here so the two layers can
never drift into representing the same concept two different ways.
"""

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"


class BusinessVertical(StrEnum):
    """Extensible on purpose (Section 4 of the master context: don't
    hardcode the product to the reformas vertical). New verticals are added
    here as they're validated with real clients; OTHER is the escape hatch
    until then."""

    HOME_RENOVATION = "home_renovation"
    REAL_ESTATE = "real_estate"
    CLINIC = "clinic"
    AGENCY = "agency"
    B2B_SERVICES = "b2b_services"
    RESTAURANT = "restaurant"
    ECOMMERCE = "ecommerce"
    HOTEL = "hotel"
    OTHER = "other"


class BusinessStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"


class DeployTarget(StrEnum):
    CLOUDFLARE = "cloudflare"


class WebsiteStatus(StrEnum):
    DRAFT = "draft"
    BUILDING = "building"
    LIVE = "live"
    FAILED = "failed"
    # Was LIVE, deliberately taken offline via POST .../website/deactivate
    # (app.publishing.service.unpublish_website) — distinct from DRAFT
    # ("never published") and FAILED ("last publish attempt failed").
    # Mirrors WorkflowStatus.INACTIVE's same "was active, now turned off"
    # shape.
    INACTIVE = "inactive"


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class WorkflowVersionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"


class ConfigOrigin(StrEnum):
    """Who produced a given WorkflowVersion's definition — the AI proposal
    or a human edit. Mirrors the master context's Section 5 requirement
    that every generated artifact's provenance stay traceable."""

    AI = "ai"
    HUMAN = "human"


class IntegrationProvider(StrEnum):
    """MVP scope only (Section 9's stated priority order). Extend as later
    providers are added — Outlook, Teams, Drive, Notion, Salesforce,
    WhatsApp, Telegram."""

    WEBHOOK = "webhook"
    GMAIL = "gmail"
    GOOGLE_SHEETS = "google_sheets"
    SLACK = "slack"
    HUBSPOT = "hubspot"


class IntegrationStatus(StrEnum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ExecutionType(StrEnum):
    WORKFLOW_RUN = "workflow_run"
    WEBSITE_BUILD = "website_build"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TemplateKind(StrEnum):
    WEBSITE_BLOCK = "website_block"
    WORKFLOW_PATTERN = "workflow_pattern"


class Weekday(StrEnum):
    """Used by BusinessProfile's business_hours (app.domain.business_config)
    — a controlled vocabulary in place of packages/site-config's
    LocalBusinessOpeningHours.dayOfWeek, which is free-text on the
    TypeScript side (schema.org's DayOfWeek values) because that layer is
    trusted, hand-authored content. This layer isn't."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class LeadSource(StrEnum):
    """Where a lead can come from — Section 8's stated initial set."""

    WEBSITE_FORM = "website_form"
    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    MANUAL = "manual"
    OTHER = "other"


class LeadStatus(StrEnum):
    """A lead's basic follow-up state. Deliberately just these four —
    not a CRM pipeline: no custom stages, no per-tenant configurability.
    NEW is always where a lead starts (see Lead.status's default);
    CONTACTED/WON/LOST are set by a human via PATCH
    /businesses/{id}/leads/{id}/status, never by the system itself."""

    NEW = "new"
    CONTACTED = "contacted"
    # Added in P0: a lead the business has actively engaged with and
    # judged a real prospect, distinct from merely CONTACTED (which only
    # means "we reached out," not "this looks like a real opportunity").
    QUALIFIED = "qualified"
    WON = "won"
    LOST = "lost"


class BrandStrategy(StrEnum):
    """How much of a business's existing visual identity a creative
    generation request should preserve versus reimagine. A typed domain
    concept per the Creative Orchestrator brief (Section 5) rather than
    an arbitrary string scattered across CreativeConfig/CreativeBrief/
    CreativeProvider — every layer that branches on strategy branches on
    one of exactly these three values."""

    # Keep logo, brand colors, photography, recognizable visual identity;
    # improve layout, UX, typography, hierarchy, responsiveness, motion.
    PRESERVE = "preserve"
    # Preserve brand recognition while allowing color system, typography,
    # layout, art direction and visual language to evolve.
    EVOLVE = "evolve"
    # Use business information as context but allow a substantially new
    # creative direction; real business facts must still stay accurate.
    NEW_DIRECTION = "new_direction"


class CreativeLevel(StrEnum):
    """How premium a creative generation request is — what
    CreativeOrchestrator.select_provider (app.creative.orchestrator) uses
    to route between InternalCreativeProvider and a premium provider like
    Higgsfield. No pricing is encoded here (Section 12: "do not hardcode
    pricing yet") — this is purely a capability/routing signal."""

    BASIC = "basic"
    PROFESSIONAL = "professional"
    PREMIUM = "premium"
    CINEMATIC = "cinematic"


class CreativeProviderName(StrEnum):
    """Which CreativeProvider implementation (app.creative.provider)
    produced or should produce a CreativeGeneration. Stored via str_enum
    (native_enum=False, see app.db.models.columns) rather than a native DB
    enum specifically so a future provider (OpenAI, Replicate, Flux — see
    the master context's Section 8 provider list) is addable here without
    a migration, the same reasoning app.db.models.integration.Integration
    already relies on for IntegrationProvider."""

    INTERNAL = "internal"
    HIGGSFIELD = "higgsfield"


class CreativeGenerationType(StrEnum):
    """What kind of creative output a CreativeGeneration request targets
    — mirrors CreativeProvider's five capability methods (Section 8) minus
    generate_concept/generate_website's overlap: WEBSITE_CONCEPT is a
    cheap early-stage art-direction pass, WEBSITE the full generation."""

    WEBSITE_CONCEPT = "website_concept"
    WEBSITE = "website"
    IMAGE = "image"
    VIDEO = "video"
    VISUAL_ASSET = "visual_asset"
    CREATIVE_DIRECTION = "creative_direction"


class CreativeGenerationStatus(StrEnum):
    """A CreativeGeneration's lifecycle (Section 19 of the master
    context). Mirrors ExecutionStatus's shape plus CANCELLED — an
    external creative provider call, unlike an internal Execution, can be
    a long-running job a caller explicitly cancels. Never regresses from
    a terminal state (COMPLETED/FAILED/CANCELLED) back to PENDING/
    RUNNING; enforced by app.creative.orchestrator, not a DB constraint."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssetKind(StrEnum):
    """The physical media type of a BusinessAsset row (Section 2)."""

    LOGO = "logo"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class AssetCategory(StrEnum):
    """What a BusinessAsset depicts/is for — Section 3's classification
    taxonomy. Every asset starts as OTHER until classified (by a human in
    Studio today; app.creative.classification's AssetClassifier interface
    is the clean boundary Section 3 asks for once automatic classification
    exists) — LOW_QUALITY marks an asset a classifier or human has flagged
    as unsuitable for use, never silently excluded any other way."""

    LOGO = "logo"
    PROJECT = "project"
    TEAM = "team"
    FACILITY = "facility"
    PRODUCT = "product"
    BEFORE = "before"
    AFTER = "after"
    HERO_CANDIDATE = "hero_candidate"
    GALLERY = "gallery"
    OTHER = "other"
    LOW_QUALITY = "low_quality"


class AssetOrigin(StrEnum):
    """Where a BusinessAsset actually came from — the provenance Section
    1's "real business content > generated content" rule depends on:
    CreativeBrief construction (app.domain.creative.brief) prefers
    UPLOADED/IMPORTED assets over GENERATED ones for the same category."""

    UPLOADED = "uploaded"
    IMPORTED = "imported"
    GENERATED = "generated"


class WebsiteDraftStatus(StrEnum):
    """A generated website's safe pre-publish lifecycle — the "safe draft/
    version" this task's Phase 6/7 asks for, kept entirely separate from
    `WebsiteStatus` (the *live*, already-published site's own status).
    `PUBLISHED` here only ever follows `APPROVED`: nothing in this
    codebase transitions a draft straight from BUILD_FAILED/READY to
    PUBLISHED, so "generation alone never publishes" holds by construction
    in the state machine itself, not only by convention."""

    DRAFT = "draft"
    BUILDING = "building"
    # Built successfully (a real `astro build` succeeded) — safe to
    # preview and approve. May still carry non-blocking `validation_issues`
    # (app.qa.validate) for a human to weigh before approving.
    READY = "ready"
    BUILD_FAILED = "build_failed"
    APPROVED = "approved"
    PUBLISHED = "published"


class ConsentCategory(StrEnum):
    """The fixed vocabulary a generated site's cookie-consent banner
    (apps.site-builder's CookieConsentBanner) and any non-essential
    script it ever loads are built around (P0 Phase 16-19's "real
    consent architecture" requirement). NECESSARY is never optional and
    never shown as a toggle — everything else defaults to withheld and
    is only granted by an explicit, unpreselected visitor choice. A
    future non-essential block/integration (analytics, marketing pixel,
    a reviews widget) declares one of these, and its script is gated on
    that category actually being granted before this codebase ever loads
    it — see packages/website-generator's consent module and
    apps/site-builder's CookieConsentBanner for where that's enforced."""

    NECESSARY = "necessary"
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    PREFERENCES = "preferences"


class DomainStatus(StrEnum):
    """A CustomDomain's lifecycle (P0 Phase 11-15). PENDING_VERIFICATION
    covers everything Cloudflare hasn't yet reported as its own "active"
    state — this codebase never asserts a finer-grained reading of
    Cloudflare's own status than that, since the exact intermediate
    values aren't a contract this app depends on. ACTIVE only follows a
    real CloudflarePagesDomainProvider response reporting the hostname
    active; ERROR is set on a provider failure the human must act on;
    REMOVED mirrors WebsiteStatus.INACTIVE's shape — detached for real,
    row kept rather than deleted."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    ERROR = "error"
    REMOVED = "removed"


class NotificationDeliveryStatus(StrEnum):
    """The outcome of one email-delivery attempt (P1.2) — used by both
    InternalNotification.status (the business's own team) and Lead.
    acknowledgement_status (the visitor's confirmation email), never
    conflated with Lead.status (app.domain.enums.LeadStatus), which is
    the lead's own follow-up pipeline state, a completely different
    concept. NOT_CONFIGURED and PENDING are both non-failure states —
    the distinction is deliberate: NOT_CONFIGURED means no attempt was
    made because no provider/recipient/consent existed, PENDING means an
    attempt hasn't happened yet at all (the row's transient initial
    value before the same request's delivery attempt runs)."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


class ReviewSource(StrEnum):
    """Where a BusinessReview was obtained from (Section 4). GOOGLE is
    the target integration; MANUAL covers a review entered by hand today
    since no live Google Reviews API credential/integration exists yet in
    this codebase."""

    GOOGLE = "google"
    MANUAL = "manual"
    OTHER = "other"


class AnalyticsEventType(StrEnum):
    """P1.7's fixed event taxonomy — a closed vocabulary, never a
    free-text event name a caller could invent, so aggregation
    (app.analytics_events.metrics) never has to guess what a given event
    means. PAGE_VIEW/CTA_CLICK/WHATSAPP_CLICK/LEAD_FORM_STARTED/
    PHONE_CLICK/EMAIL_CLICK are all client-side visitor-behavior events,
    gated on ConsentCategory.ANALYTICS before a generated site ever fires
    one (see apps/site-builder's analytics script). LEAD_SUBMITTED is
    the one exception worth naming explicitly: it exists here only for
    optional client-side funnel context (page_view -> cta_click ->
    lead_form_started -> lead_submitted); the *authoritative* count of
    real leads is always app.db.models.lead.Lead itself — a functional,
    consent-independent record of a requested service, never gated on
    analytics consent the way this event is."""

    PAGE_VIEW = "page_view"
    CTA_CLICK = "cta_click"
    WHATSAPP_CLICK = "whatsapp_click"
    LEAD_FORM_STARTED = "lead_form_started"
    LEAD_SUBMITTED = "lead_submitted"
    PHONE_CLICK = "phone_click"
    EMAIL_CLICK = "email_click"


class GenerationEngine(StrEnum):
    """Which pipeline actually produced a WebsiteDraft's implementation
    (P2): DETERMINISTIC is the existing, unchanged
    packages/website-generator `generateSiteConfig()` -> blocks -> Astro
    pipeline (WebsiteDraft.site_config carries its output); GENERATIVE is
    the new CreativeDirection -> AI Frontend Engineer pipeline
    (app.creative.frontend_engine), whose output is a
    GenerativeWebsiteArtifact (app.db.models.generative_website_artifact)
    instead of a SiteConfig. A draft's `engine` decides which of the two
    is populated — never both, never neither. Engine selection is always
    explicit (a caller states which engine it wants); nothing in this
    codebase silently falls back from GENERATIVE to DETERMINISTIC and
    reports it as a successful generative result — a failed generative
    attempt surfaces as a FAILED/BUILD_FAILED state, honestly."""

    DETERMINISTIC = "deterministic"
    GENERATIVE = "generative"


class CreativeBudgetTier(StrEnum):
    """A named credit-spend ceiling for one Higgsfield creative-direction
    workflow run (app.domain.creative.budget) — not a pricing plan sold to
    a business, purely an internal control on how much a single
    create_directions + develop_direction workflow is allowed to spend.
    EXPERIMENTAL carries no built-in default hard limit (see
    app.domain.creative.budget.DEFAULT_TIER_LIMITS) — a caller must state
    one explicitly, never inherit an implicit ceiling for a tier whose
    whole point is "we don't have a settled number yet"."""

    STANDARD = "standard"
    PREMIUM = "premium"
    EXPERIMENTAL = "experimental"


class PlatformContractSeverity(StrEnum):
    """How a PlatformContract finding (app.qa.platform_contract) affects a
    WebsiteDraft's QA outcome. BLOCKING mirrors WebsiteDraftStatus's
    existing BUILD_FAILED gate: a draft carrying any BLOCKING violation can
    never be approved (P2.8's "must never reach an approved/publishable
    state with decorative dead CTAs" is enforced here, not only by
    convention). ADVISORY mirrors app.qa.validate's existing
    `validation_issues` — visible to a human before approving, never
    itself blocking."""

    BLOCKING = "blocking"
    ADVISORY = "advisory"


class HealthStatus(StrEnum):
    """A single vocabulary for both one sub-check's outcome (HTTP, DNS,
    TLS, deployment, contact form) and WebsiteHealthCheck's own overall
    rollup (P1.4) — deliberately the same four values at both levels
    rather than two separate enums, since "the overall state is the
    worst of its parts" is simplest to express when both sides speak the
    same vocabulary. UNKNOWN means "not (yet) checked, or the business
    has nothing to check yet (no published website)" — never conflated
    with HEALTHY; a caller must never render UNKNOWN as if it were a
    passing check."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"
