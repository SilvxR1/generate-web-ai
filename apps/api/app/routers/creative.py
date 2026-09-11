from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.creative.errors import CreativeProviderError
from app.creative.higgsfield import HiggsfieldCreativeProvider
from app.creative.orchestrator import orchestrate_generation
from app.creative.provider import CreativeProvider
from app.db.models.business_asset import BusinessAsset
from app.db.models.business_review import BusinessReview
from app.dependencies import (
    get_current_tenant_id,
    get_google_review_provider,
    get_internal_creative_provider,
    get_manual_review_provider,
    get_optional_higgsfield_provider,
    get_session,
    get_storage_provider,
    get_website_publisher,
    rate_limit_dependency,
)
from app.domain.business_config import BusinessConfig, CreativeConfig
from app.domain.enums import AssetCategory, AssetKind, AssetOrigin, CreativeProviderName
from app.errors import AppError
from app.publishing.drafts import (
    WebsiteDraftError,
    approve_website_draft,
    create_website_draft,
    publish_website_draft,
)
from app.publishing.publisher import WebsitePublisher
from app.publishing.service import WebsitePublishError, WebsiteStateResult
from app.repositories.business_asset import BusinessAssetRepository
from app.repositories.business_review import BusinessReviewRepository
from app.repositories.creative_generation import CreativeGenerationRepository
from app.repositories.website_draft import WebsiteDraftRepository
from app.reviews.provider import GoogleReviewProvider, ManualReviewProvider
from app.schemas.creative import (
    BusinessAssetCreateRequest,
    BusinessAssetRead,
    BusinessAssetUpdateRequest,
    BusinessAssetUploadResult,
    BusinessReviewCreateRequest,
    BusinessReviewRead,
    BusinessReviewVisibilityUpdateRequest,
    CreativeGenerationRead,
    CreativeGenerationRequest,
    CreativeProviderAvailability,
    ReviewProviderAvailability,
)
from app.schemas.website_draft import WebsiteDraftCreateRequest, WebsiteDraftRead
from app.services.business_service import BusinessNotFoundError, BusinessService
from app.storage import StorageProvider, generate_storage_key

router = APIRouter(prefix="/businesses/{business_id}", tags=["creative"])

# Phase 3's stated minimum ("logo, image") plus video/document so the
# validation boundary is already extensible without a router change —
# nothing beyond image/logo is exercised by Studio yet, and no
# video/3D processing exists anywhere in this codebase.
_ALLOWED_UPLOAD_CONTENT_TYPES: dict[AssetKind, frozenset[str]] = {
    AssetKind.LOGO: frozenset({"image/jpeg", "image/png", "image/webp", "image/svg+xml"}),
    AssetKind.IMAGE: frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"}),
    AssetKind.VIDEO: frozenset({"video/mp4", "video/webm", "video/quicktime"}),
    AssetKind.DOCUMENT: frozenset({"application/pdf"}),
}


def _not_found() -> AppError:
    return AppError("Business not found.", code="business_not_found", status_code=status.HTTP_404_NOT_FOUND)


def _asset_not_found() -> AppError:
    return AppError("Asset not found.", code="business_asset_not_found", status_code=status.HTTP_404_NOT_FOUND)


def _review_not_found() -> AppError:
    return AppError("Review not found.", code="business_review_not_found", status_code=status.HTTP_404_NOT_FOUND)


def _draft_error(exc: WebsiteDraftError) -> AppError:
    return AppError(str(exc), code=exc.code, status_code=exc.status_code)


def _get_business(session: Session, tenant_id: UUID, business_id: UUID):
    try:
        return BusinessService(session).get(tenant_id, business_id)
    except BusinessNotFoundError as exc:
        raise _not_found() from exc


def _load_business_config(session: Session, tenant_id: UUID, business_id: UUID) -> BusinessConfig | None:
    business = _get_business(session, tenant_id, business_id)
    if business.config is None:
        return None
    return BusinessConfig.model_validate(business.config)


# --- Provider availability (Phase 13) -----------------------------------


@router.get("/creative-providers", response_model=list[CreativeProviderAvailability])
def list_creative_provider_availability(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    internal_provider: CreativeProvider = Depends(get_internal_creative_provider),
    premium_provider: CreativeProvider | None = Depends(get_optional_higgsfield_provider),
) -> list[CreativeProviderAvailability]:
    """Honest, real-config-backed provider availability — never a
    hardcoded UI placeholder; `available`/`unavailable_reason` reflect
    exactly what app.dependencies.get_higgsfield_provider itself would do
    right now. `business_id`/`tenant_id` authenticate the caller the same
    way GET .../automation-recommendation does on the businesses router —
    this response is identical for every business a tenant owns, never
    business-specific data."""
    del business_id, tenant_id
    providers = [
        CreativeProviderAvailability(
            provider=internal_provider.name,
            available=True,
            capabilities=sorted(internal_provider.capabilities, key=lambda c: c.value),
        )
    ]
    if premium_provider is not None:
        providers.append(
            CreativeProviderAvailability(
                provider=premium_provider.name,
                available=True,
                capabilities=sorted(premium_provider.capabilities, key=lambda c: c.value),
            )
        )
    else:
        providers.append(
            CreativeProviderAvailability(
                provider=CreativeProviderName.HIGGSFIELD,
                available=False,
                capabilities=sorted(HiggsfieldCreativeProvider.capabilities, key=lambda c: c.value),
                unavailable_reason="Higgsfield is not configured on this server.",
            )
        )
    return providers


# --- Business asset library (Section 2/3) -----------------------------


@router.post("/assets", response_model=BusinessAssetRead, status_code=status.HTTP_201_CREATED)
def create_business_asset(
    business_id: UUID,
    payload: BusinessAssetCreateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> BusinessAsset:
    """Registers one real or generated asset for this business's library
    (Section 14: reusable across future generations, not disposable
    single-request context). Does not upload or host any file itself —
    `storage_url` must already point at wherever the asset lives (Section
    2: no new storage backend before one exists)."""
    _get_business(session, tenant_id, business_id)
    asset = BusinessAsset(tenant_id=tenant_id, business_id=business_id, **payload.model_dump())
    return BusinessAssetRepository(session).add(asset)


def _save_uploaded_asset(
    *,
    request: Request,
    business_id: UUID,
    tenant_id: UUID,
    session: Session,
    storage: StorageProvider,
    file: UploadFile,
    kind: AssetKind,
    category: AssetCategory,
    alt_text: str | None,
) -> BusinessAsset:
    """The actual validate-then-save logic behind both single-file
    upload (below) and the multi-file batch endpoint (LR-01) — one
    implementation, so "upload 15 photos" is 15 calls to the same
    validated path, not a second copy of it. Raises `AppError` on any
    validation failure; the batch endpoint catches that per file so one
    bad file never loses the others (LR-01's "show per-file failures
    without losing successful uploads")."""
    allowed_content_types = _ALLOWED_UPLOAD_CONTENT_TYPES.get(kind)
    if not allowed_content_types or file.content_type not in allowed_content_types:
        raise AppError(
            f"Unsupported content type {file.content_type!r} for asset kind {kind.value!r}.",
            code="unsupported_asset_content_type",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    # Read one byte past the limit so an oversized upload is detected
    # without ever buffering more than max_upload_size_bytes + 1 into
    # memory — this backend has no queue/streaming-to-disk pipeline for
    # uploads, so bounding the in-memory read is the whole size guard.
    content = file.file.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise AppError(
            f"File exceeds the maximum upload size of {settings.max_upload_size_bytes} bytes.",
            code="asset_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    if not content:
        raise AppError("Uploaded file is empty.", code="empty_asset_upload", status_code=status.HTTP_400_BAD_REQUEST)

    storage_key = generate_storage_key(business_id=str(business_id), original_filename=file.filename or "upload")
    storage.save(storage_key=storage_key, content=content)
    # request.base_url reflects however this request actually reached the
    # server (host/scheme/port) — never a hardcoded setting, so this
    # works unchanged in dev, behind a proxy, or in production alike.
    storage_url = str(request.base_url).rstrip("/") + storage.url_path(storage_key)

    asset = BusinessAsset(
        tenant_id=tenant_id,
        business_id=business_id,
        kind=kind,
        category=category,
        origin=AssetOrigin.UPLOADED,
        storage_url=storage_url,
        original_filename=file.filename,
        alt_text=alt_text,
    )
    return BusinessAssetRepository(session).add(asset)


@router.post("/assets/upload", response_model=BusinessAssetRead, status_code=status.HTTP_201_CREATED)
def upload_business_asset(
    request: Request,
    business_id: UUID,
    file: UploadFile = File(...),
    kind: AssetKind = Form(...),
    category: AssetCategory = Form(AssetCategory.OTHER),
    alt_text: str | None = Form(None),
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
    _rate_limit: None = Depends(
        rate_limit_dependency(key_prefix="asset_upload", limit_attr="asset_upload_rate_limit_per_minute")
    ),
) -> BusinessAsset:
    """Real file ingestion (Phase 3) — the counterpart to POST .../assets
    above, for a file the caller has on hand rather than one already
    hosted somewhere. Always creates a new asset with `origin=UPLOADED` —
    replacing an existing one (e.g. swapping the logo) is delete-then-
    upload, not an update, since `storage_url`/`storage_key` are
    provenance facts this endpoint owns, not user-editable state (see
    PATCH .../assets/{id} for what *is* editable: category/alt_text).
    See `_save_uploaded_asset` for the actual validate-then-save logic,
    shared with the multi-file batch endpoint below."""
    _get_business(session, tenant_id, business_id)
    return _save_uploaded_asset(
        request=request,
        business_id=business_id,
        tenant_id=tenant_id,
        session=session,
        storage=storage,
        file=file,
        kind=kind,
        category=category,
        alt_text=alt_text,
    )


@router.post(
    "/assets/upload-batch",
    response_model=list[BusinessAssetUploadResult],
    status_code=status.HTTP_207_MULTI_STATUS,
)
def upload_business_assets_batch(
    request: Request,
    business_id: UUID,
    files: list[UploadFile] = File(...),
    kind: AssetKind = Form(...),
    category: AssetCategory = Form(AssetCategory.OTHER),
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    storage: StorageProvider = Depends(get_storage_provider),
    _rate_limit: None = Depends(
        rate_limit_dependency(key_prefix="asset_upload", limit_attr="asset_upload_rate_limit_per_minute")
    ),
) -> list[BusinessAssetUploadResult]:
    """Multi-file upload (LR-01) — "select 15 photos, upload once"
    instead of repeating the single-file form 15 times. `kind`/`category`
    apply to every file in the batch (the common real case: a batch of
    business photos, or a batch of gallery images); a file that needs a
    different classification can still be reclassified afterward via
    PATCH .../assets/{id}, or uploaded on its own.

    Always returns 207 Multi-Status with one result per file, in the
    same order they were sent — a failure on file 7 of 15 never discards
    the 6 that already succeeded (each file gets its own DB transaction
    boundary via the shared session's autoflush, and a validation
    failure raises `AppError` caught here rather than aborting the
    request). This is the one endpoint in this router that reports
    partial failure in its response body instead of an HTTP error
    status, since "some of N files failed" isn't itself a request
    failure.
    """
    _get_business(session, tenant_id, business_id)

    results: list[BusinessAssetUploadResult] = []
    for file in files:
        try:
            asset = _save_uploaded_asset(
                request=request,
                business_id=business_id,
                tenant_id=tenant_id,
                session=session,
                storage=storage,
                file=file,
                kind=kind,
                category=category,
                alt_text=None,
            )
            results.append(
                BusinessAssetUploadResult(
                    filename=file.filename, success=True, asset=BusinessAssetRead.model_validate(asset)
                )
            )
        except AppError as exc:
            results.append(
                BusinessAssetUploadResult(filename=file.filename, success=False, error=str(exc), asset=None)
            )
    return results


@router.get("/assets", response_model=list[BusinessAssetRead])
def list_business_assets(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[BusinessAsset]:
    _get_business(session, tenant_id, business_id)
    return BusinessAssetRepository(session).list_for_business(tenant_id, business_id)


@router.patch("/assets/{asset_id}", response_model=BusinessAssetRead)
def update_business_asset(
    business_id: UUID,
    asset_id: UUID,
    payload: BusinessAssetUpdateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> BusinessAsset:
    """Reclassifying an asset (Section 3's classification categories) —
    the one write this endpoint supports; provenance fields
    (storage_url/origin/kind) are never editable here."""
    _get_business(session, tenant_id, business_id)
    repo = BusinessAssetRepository(session)
    asset = repo.get_for_business(tenant_id, business_id, asset_id)
    if asset is None:
        raise _asset_not_found()
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    session.flush()
    return asset


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business_asset(
    business_id: UUID,
    asset_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> None:
    _get_business(session, tenant_id, business_id)
    repo = BusinessAssetRepository(session)
    if repo.get_for_business(tenant_id, business_id, asset_id) is None:
        raise _asset_not_found()
    repo.delete(tenant_id, asset_id)


# --- Google/manual reviews (Section 4) ---------------------------------


@router.post("/reviews", response_model=BusinessReviewRead, status_code=status.HTTP_201_CREATED)
def create_business_review(
    business_id: UUID,
    payload: BusinessReviewCreateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> BusinessReview:
    """Registers a review the caller asserts is real — never fabricated
    by this endpoint, and never altered afterward (Section 4)."""
    _get_business(session, tenant_id, business_id)
    review = BusinessReview(tenant_id=tenant_id, business_id=business_id, **payload.model_dump())
    return BusinessReviewRepository(session).add(review)


@router.get("/reviews", response_model=list[BusinessReviewRead])
def list_business_reviews(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[BusinessReview]:
    _get_business(session, tenant_id, business_id)
    return BusinessReviewRepository(session).list_for_business(tenant_id, business_id)


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business_review(
    business_id: UUID,
    review_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> None:
    _get_business(session, tenant_id, business_id)
    repo = BusinessReviewRepository(session)
    if repo.get_for_business(tenant_id, business_id, review_id) is None:
        raise _review_not_found()
    repo.delete(tenant_id, review_id)


@router.patch("/reviews/{review_id}/visibility", response_model=BusinessReviewRead)
def update_business_review_visibility(
    business_id: UUID,
    review_id: UUID,
    payload: BusinessReviewVisibilityUpdateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> BusinessReview:
    """P1.6: show/hide a review on the generated website without
    deleting it — provenance (source/body/rating/raw_payload) is
    untouched either way."""
    _get_business(session, tenant_id, business_id)
    repo = BusinessReviewRepository(session)
    review = repo.get_for_business(tenant_id, business_id, review_id)
    if review is None:
        raise _review_not_found()
    review.is_visible = payload.is_visible
    session.flush()
    return review


@router.get("/review-providers", response_model=list[ReviewProviderAvailability])
def list_review_provider_availability(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    manual_provider: ManualReviewProvider = Depends(get_manual_review_provider),
    google_provider: GoogleReviewProvider = Depends(get_google_review_provider),
) -> list[ReviewProviderAvailability]:
    """Honest, real-config-backed provider availability (P1.6/P1.12) —
    same shape as GET .../creative-providers above. This response is
    identical for every business a tenant owns."""
    del business_id, tenant_id
    return [
        ReviewProviderAvailability(
            provider=manual_provider.source, available=manual_provider.is_available(), unavailable_reason=None
        ),
        ReviewProviderAvailability(
            provider=google_provider.source,
            available=google_provider.is_available(),
            unavailable_reason=google_provider.unavailable_reason(),
        ),
    ]


# --- Creative strategy/level config (Section 5/12) ----------------------


@router.get("/creative-config", response_model=CreativeConfig)
def get_business_creative_config(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> CreativeConfig:
    """Returns the default CreativeConfig (strategy=EVOLVE, level=BASIC)
    for a business with no config yet, the same "sensible default, not an
    error" convention CreativeConfig's own field defaults already
    express."""
    config = _load_business_config(session, tenant_id, business_id)
    return config.creative if config else CreativeConfig()


@router.put("/creative-config", response_model=CreativeConfig)
def update_business_creative_config(
    business_id: UUID,
    payload: CreativeConfig,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> CreativeConfig:
    """Requires the business to already have a BusinessConfig (same
    "nothing to update yet" 409 as POST .../automation/activate) — a
    business's creative strategy/level is meaningless without the rest of
    its configuration to apply it to."""
    business = _get_business(session, tenant_id, business_id)
    if business.config is None:
        raise AppError(
            "This business has no configuration yet.", code="no_business_config", status_code=status.HTTP_409_CONFLICT
        )
    config = BusinessConfig.model_validate(business.config)
    config.creative = payload
    business.config = config.model_dump(mode="json")
    session.flush()
    return payload


# --- Creative generation (Section 11/13/16) -----------------------------


@router.post("/creative-generations", response_model=CreativeGenerationRead, status_code=status.HTTP_201_CREATED)
def create_creative_generation(
    business_id: UUID,
    payload: CreativeGenerationRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    internal_provider: CreativeProvider = Depends(get_internal_creative_provider),
    premium_provider: CreativeProvider | None = Depends(get_optional_higgsfield_provider),
) -> object:
    """Runs one CreativeOrchestrator generation and persists it —
    generate, regenerate, and "generate a variation" are all the same
    call (Section 16); the currently published website is never touched
    by this endpoint (see app.creative.orchestrator's own docstring)."""
    config = _load_business_config(session, tenant_id, business_id)
    if config is None:
        raise AppError(
            "This business has no configuration to generate from.",
            code="no_business_config",
            status_code=status.HTTP_409_CONFLICT,
        )

    assets = BusinessAssetRepository(session).list_for_business(tenant_id, business_id)
    reviews = BusinessReviewRepository(session).list_for_business(tenant_id, business_id)

    try:
        return orchestrate_generation(
            session=session,
            tenant_id=tenant_id,
            business_id=business_id,
            business_config=config,
            generation_type=payload.generation_type,
            internal_provider=internal_provider,
            premium_provider=premium_provider,
            assets=assets,
            reviews=reviews,
        )
    except CreativeProviderError as exc:
        raise AppError(str(exc), code="creative_provider_error", status_code=status.HTTP_502_BAD_GATEWAY) from exc


@router.get("/creative-generations", response_model=list[CreativeGenerationRead])
def list_creative_generations(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[object]:
    """Every generation attempt for this business, most recent first —
    the traceability history Section 13 describes."""
    _get_business(session, tenant_id, business_id)
    return list(CreativeGenerationRepository(session).list_for_business(tenant_id, business_id))


# --- Website drafts: safe generate -> build -> validate -> preview ->
# --- approve -> publish (Phase 6/7/9/10) --------------------------------


@router.post("/website-drafts", response_model=WebsiteDraftRead, status_code=status.HTTP_201_CREATED)
def create_website_draft_route(
    business_id: UUID,
    payload: WebsiteDraftCreateRequest,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> object:
    """Persists a generated SiteConfig as a safe draft and immediately
    builds + validates it (app.publishing.drafts.create_website_draft) —
    never publishes. The currently published website (if any) is
    completely untouched by this call, whether the build succeeds or
    fails. Passes the business's own BusinessConfig so the build is also
    scanned against the P2 PlatformContract (app.qa.platform_contract) —
    the same contract a GENERATIVE draft is held to."""
    _get_business(session, tenant_id, business_id)
    business_config = _load_business_config(session, tenant_id, business_id)
    return create_website_draft(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        business_config=business_config,
        site_config=payload.site_config,
        creative_generation_id=payload.creative_generation_id,
    )


@router.get("/website-drafts", response_model=list[WebsiteDraftRead])
def list_website_drafts(
    business_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> list[object]:
    """Every draft ever created for this business, most recent first —
    distinct from GET .../website (the currently *published* site's own
    state), matching Phase 9's "Studio must distinguish clearly between
    CURRENT PUBLISHED WEBSITE and GENERATED PREVIEW"."""
    _get_business(session, tenant_id, business_id)
    return list(WebsiteDraftRepository(session).list_for_business(tenant_id, business_id))


@router.get("/website-drafts/{draft_id}", response_model=WebsiteDraftRead)
def get_website_draft(
    business_id: UUID,
    draft_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> object:
    """The full record, including `site_config` — what Studio's existing
    SiteConfigPreview component renders as the generated preview."""
    _get_business(session, tenant_id, business_id)
    draft = WebsiteDraftRepository(session).get_for_business(tenant_id, business_id, draft_id)
    if draft is None:
        raise AppError(
            "Website draft not found.", code="website_draft_not_found", status_code=status.HTTP_404_NOT_FOUND
        )
    return draft


@router.post("/website-drafts/{draft_id}/approve", response_model=WebsiteDraftRead)
def approve_website_draft_route(
    business_id: UUID,
    draft_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
) -> object:
    """The explicit human action between preview and publish (Phase 10) —
    only a READY (successfully built) draft can be approved; approving
    never publishes anything by itself."""
    _get_business(session, tenant_id, business_id)
    try:
        return approve_website_draft(session=session, tenant_id=tenant_id, business_id=business_id, draft_id=draft_id)
    except WebsiteDraftError as exc:
        raise _draft_error(exc) from exc


@router.post("/website-drafts/{draft_id}/publish", response_model=WebsiteStateResult)
def publish_website_draft_route(
    business_id: UUID,
    draft_id: UUID,
    tenant_id: UUID = Depends(get_current_tenant_id),
    session: Session = Depends(get_session),
    publisher: WebsitePublisher = Depends(get_website_publisher),
) -> WebsiteStateResult:
    """The one call that actually goes live — requires an APPROVED draft
    (Phase 10: generation/build/validation alone never publish). Reuses
    the existing website-publish machinery unchanged
    (app.publishing.drafts.publish_website_draft); on failure, the
    previously live site (if any) is left exactly as it was, and this
    draft stays APPROVED — safe to retry."""
    _get_business(session, tenant_id, business_id)
    try:
        return publish_website_draft(
            session=session,
            tenant_id=tenant_id,
            business_id=business_id,
            draft_id=draft_id,
            publisher=publisher,
            n8n_base_url=settings.n8n_base_url,
        )
    except WebsiteDraftError as exc:
        raise _draft_error(exc) from exc
    except WebsitePublishError as exc:
        raise AppError(str(exc), code=exc.code, status_code=exc.status_code) from exc
