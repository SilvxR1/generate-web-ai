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
