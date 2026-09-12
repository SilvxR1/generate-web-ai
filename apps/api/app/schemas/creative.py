import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    CreativeGenerationStatus,
    CreativeGenerationType,
    CreativeLevel,
    CreativeProviderName,
    ReviewSource,
)


class BusinessAssetCreateRequest(BaseModel):
    """Body for POST /businesses/{id}/assets. Registers an asset this
    codebase does not itself host — `storage_url` is wherever the caller
    already put the file (Section 2 explicitly says not to build a new
    upload/storage backend before one exists). `origin` is required, not
    defaulted: a caller must say whether this is real business content
    (UPLOADED/IMPORTED) or provider output (GENERATED) — never guessed."""

    model_config = ConfigDict(extra="forbid")

    kind: AssetKind
    category: AssetCategory = AssetCategory.OTHER
    origin: AssetOrigin
    storage_url: str = Field(min_length=1, max_length=2048)
    original_filename: str | None = Field(default=None, max_length=300)
    alt_text: str | None = Field(default=None, max_length=300)


class BusinessAssetUpdateRequest(BaseModel):
    """Body for PATCH /businesses/{id}/assets/{asset_id} — reclassifying
    an asset (Section 3's classification categories) is the one write
    this endpoint supports; `storage_url`/`origin` are provenance facts,
    not editable here."""

    model_config = ConfigDict(extra="forbid")

    category: AssetCategory | None = None
    alt_text: str | None = Field(default=None, max_length=300)


class BusinessAssetRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    kind: AssetKind
    category: AssetCategory
    origin: AssetOrigin
    storage_url: str
    original_filename: str | None
    alt_text: str | None
    generation_id: uuid.UUID | None
    created_at: datetime


class BusinessAssetUploadResult(BaseModel):
    """One file's outcome from POST .../assets/upload-batch (LR-01) —
    `asset` is set only when `success` is true, `error` only when it's
    false, so a caller never has to guess which half of a partially
    successful batch actually persisted."""

    model_config = ConfigDict(extra="forbid")

    filename: str | None
    success: bool
    asset: BusinessAssetRead | None = None
    error: str | None = None


class BusinessReviewCreateRequest(BaseModel):
    """Body for POST /businesses/{id}/reviews. Registers a review the
    caller asserts is real (Section 4: "NEVER fabricate reviews") —
    this endpoint does not call any external API on the caller's behalf;
    `source`/`source_review_id`/`review_url` exist purely to preserve
    whatever provenance the caller already has (e.g. pasting a real
    Google review's text and public URL), never validated against a live
    provider."""

    model_config = ConfigDict(extra="forbid")

    source: ReviewSource = ReviewSource.MANUAL
    source_review_id: str | None = Field(default=None, max_length=300)
    author_name: str | None = Field(default=None, max_length=200)
    rating: int | None = Field(default=None, ge=1, le=5)
    body: str = Field(min_length=1, max_length=5000)
    review_url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None


class BusinessReviewRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    source: ReviewSource
    source_review_id: str | None
    author_name: str | None
    rating: int | None
    body: str
    review_url: str | None
    published_at: datetime | None
    imported_at: datetime
    is_visible: bool


class BusinessReviewVisibilityUpdateRequest(BaseModel):
    """Body for PATCH /businesses/{id}/reviews/{id}/visibility (P1.6) —
    deliberately the only writable field from this endpoint; provenance
    (source/body/rating/...) is immutable once imported."""

    model_config = ConfigDict(extra="forbid")

    is_visible: bool


class ReviewProviderAvailability(BaseModel):
    """One row of GET /businesses/{id}/review-providers (P1.6/P1.12) —
    the same honest, real-config-backed availability shape as
    CreativeProviderAvailability above: `available`/`unavailable_reason`
    reflect exactly what app.reviews.provider.GoogleReviewProvider itself
    would report right now, never a hardcoded 'coming soon'."""

    model_config = ConfigDict(extra="forbid")

    provider: ReviewSource
    available: bool
    unavailable_reason: str | None = None


class CreativeGenerationRequest(BaseModel):
    """Body for POST /businesses/{id}/creative-generations — triggers one
    CreativeOrchestrator run (Section 11). Every call is safe to repeat
    (Section 16: generate, regenerate, and variation all go through this
    same endpoint; see app.creative.orchestrator's own docstring for why
    that never risks the currently published site)."""

    model_config = ConfigDict(extra="forbid")

    generation_type: CreativeGenerationType = CreativeGenerationType.WEBSITE


class CreativeProviderAvailability(BaseModel):
    """One row of GET /businesses/{id}/creative-providers (Phase 13):
    honest, real-config-backed availability — never a hardcoded 'coming
    soon' placeholder. `available` reflects exactly what
    app.dependencies.get_higgsfield_provider/get_internal_creative_provider
    would do right now, nothing inferred."""

    model_config = ConfigDict(extra="forbid")

    provider: CreativeProviderName
    available: bool
    capabilities: list[CreativeGenerationType]
    unavailable_reason: str | None = None


class CreativeGenerationRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    provider: CreativeProviderName
    generation_type: CreativeGenerationType
    creative_level: CreativeLevel
    status: CreativeGenerationStatus
    external_reference: str | None
    credits_used: float | None
    estimated_cost: float | None
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    created_at: datetime


# --- P2: CreativeDirection / generative workflow -------------------------


class CreateDirectionsRequest(BaseModel):
    """Body for POST /businesses/{id}/creative-directions (P2.3 STEP A).
    `hard_limit`/`tier` let a caller override the STANDARD default budget
    (app.domain.creative.budget) for this one exploration — never a
    silent, unbounded spend."""

    model_config = ConfigDict(extra="forbid")

    hard_limit: float | None = Field(default=None, gt=0)


class DevelopDirectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_limit: float | None = Field(default=None, gt=0)


class CreativeDirectionRead(BaseModel):
    """One candidate/developed CreativeDirection — the full free-text
    creative-intent shape (concept/visual_language/experience/
    content_strategy/references/constraints), never collapsed to an id
    a caller can't actually see or reason about (P2.13: Studio must be
    able to show *why* a direction was recommended)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    creative_generation_id: uuid.UUID | None
    concept: dict
    visual_language: dict
    experience: dict
    content_strategy: dict
    # The ORM attribute is named `references_` (see
    # app.db.models.creative_direction's own docstring for why), but the
    # public API field is plain `references` — validation_alias controls
    # how from_attributes reads the ORM object, serialization_alias
    # controls the outgoing JSON key; a plain `alias=` would have made
    # from_attributes look for a nonexistent `.references` attribute.
    references_: list[str] = Field(validation_alias="references_", serialization_alias="references")
    constraints: dict
    provider_metadata: dict
    generation_metadata: dict
    is_recommended: bool
    selection_rationale: str | None
    credits_used: float | None
    developed_at: datetime | None
    created_at: datetime


class FrontendEngineerAvailability(BaseModel):
    """GET .../frontend-engineer-availability (P2 continuation Part 1):
    a real, on-demand, verified check (app.creative.frontend_engine.
    availability.check_frontend_engineer_availability) — `available`
    means Anthropic actually accepted a real, minimal request just now,
    never merely "a key string is present". Studio uses this to show
    "AI generation unavailable: <reason>" honestly instead of only
    discovering it the first time a real generation attempt fails."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "anthropic"
    available: bool
    unavailable_reason: str | None = None


class GenerateWebsiteFromDirectionRequest(BaseModel):
    """Body for POST /businesses/{id}/website-drafts/generative (P2 Part
    A/C) — triggers the AI Frontend Engineer against one already-selected
    CreativeDirection. Never accepts a business_id/api_base_url override
    from the caller (both stay server-derived, P2 Part K's tenant-
    spoofing protection)."""

    model_config = ConfigDict(extra="forbid")

    creative_direction_id: uuid.UUID


class GenerativeArtifactRead(BaseModel):
    """GET .../website-drafts/{id}/generative-artifact (P2 continuation
    Part 4/5): the full QA record behind a generative draft — Studio's
    single source for both PlatformContract (`qa_state`) and real-browser
    Visual QA (`visual_qa_state`) results, plus the storage keys for the
    real screenshots that back it. `visual_qa_state`/`screenshot_keys`
    are `{}` until run_visual_qa_for_draft has actually run for this
    draft — never a fabricated pass."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    website_draft_id: uuid.UUID
    framework: str
    generator_provider: str
    generator_model: str | None
    platform_contract_version: str
    qa_state: dict
    visual_qa_state: dict
    screenshot_keys: dict
    generated_at: datetime
    duration_ms: int | None
