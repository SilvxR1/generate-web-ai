import hmac
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.analysis.analyzer import BusinessAnalyzer
from app.analysis.claude.engine import business_analyzer_from_settings
from app.analytics_events.provider import AnalyticsProvider, InternalAnalyticsProvider
from app.auth.service import AuthenticatedSession, resolve_session
from app.automation.n8n import N8nClient
from app.config import settings
from app.creative.artifact_fetcher import ArtifactFetcher, HttpsArtifactFetcher
from app.creative.director import CreativeDirectorProvider
from app.creative.director_fallback import FallbackCreativeDirector
from app.creative.director_internal import InternalCreativeDirector
from app.creative.frontend_engine import FrontendEngineer, frontend_engineer_from_settings
from app.creative.higgsfield import (
    HiggsfieldApiClient,
    HiggsfieldApiCreativeDirector,
    HiggsfieldCli,
    HiggsfieldCliCreativeDirector,
    HiggsfieldClient,
    HiggsfieldCreativeProvider,
)
from app.creative.internal import InternalCreativeProvider
from app.creative.provider import CreativeProvider
from app.db.models.user import User
from app.db.session import make_engine, make_session_factory
from app.errors import AppError
from app.notifications.resend import ResendNotificationSender
from app.notifications.sender import NotificationSender
from app.notifications.smtp import SmtpNotificationSender
from app.publishing.cloudflare import CloudflarePagesClient, CloudflarePagesDomainProvider, CloudflarePagesPublisher
from app.publishing.domain_provider import DomainProvider
from app.publishing.publisher import WebsitePublisher
from app.repositories.tenant import TenantRepository
from app.repositories.tenant_access import TenantAccessRepository
from app.reviews.provider import GoogleReviewProvider, ManualReviewProvider
from app.security.rate_limit import InMemoryRateLimiter, RateLimiter, RateLimitExceededError
from app.services.generated_image_qa import GeneratedImageQAService
from app.storage import CloudflareR2StorageProvider, LocalStorageProvider, StorageProvider

# Module-level: one engine/pool for the process lifetime, per SQLAlchemy's
# own recommendation (an Engine is meant to be created once, not per
# request). Tests override get_engine/get_session via FastAPI's
# dependency_overrides rather than reaching into these globals directly.
engine: Engine = make_engine(settings.database_url)
_session_factory = make_session_factory(engine)

# One rate limiter for the process lifetime — an InMemoryRateLimiter's
# whole point is per-process state (see its own docstring), so unlike
# get_session above, this is a real singleton, not just a pooled
# resource. Tests override get_rate_limiter via FastAPI's
# dependency_overrides, same as every other dependency here.
_rate_limiter: RateLimiter = InMemoryRateLimiter()


def get_engine() -> Engine:
    return engine


def get_session() -> Iterator[Session]:
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _not_authenticated() -> AppError:
    return AppError("Not authenticated.", code="not_authenticated", status_code=401)


def _unknown_tenant() -> AppError:
    # The SAME error, for BOTH "no Tenant row has this id" and "a real
    # Tenant, but this user has no TenantAccess grant for it" — telling
    # those apart would let an authenticated caller enumerate which
    # tenant UUIDs are real, exactly the tenant-UUID-enumeration risk A2's
    # own threat model calls out.
    return AppError("Unknown tenant.", code="unknown_tenant", status_code=404)


def _check_csrf(request: Request, expected_csrf_token: str) -> None:
    """Required on every mutating (non-safe-method) authenticated request
    — see app.auth.cookies' own docstring for why SameSite alone cannot be
    relied on here (production's cross-site Studio/API topology needs
    SameSite=None, which forfeits SameSite's own CSRF protection). The
    token is a value only ever handed to the legitimate caller in a
    /auth/login or /auth/me JSON response body — a cross-site attacker's
    page can trigger a request but can never read that response body
    (blocked by CORS/same-origin policy) or therefore learn the value to
    put in the header."""
    if request.method in _SAFE_METHODS:
        return
    provided = request.headers.get("x-csrf-token")
    if not provided or not hmac.compare_digest(provided, expected_csrf_token):
        raise AppError("Missing or invalid CSRF token.", code="invalid_csrf_token", status_code=403)


def get_current_session(request: Request, session: Session = Depends(get_session)) -> AuthenticatedSession:
    """The real authentication boundary (A2): resolves the opaque session
    cookie to a live, non-expired, non-revoked UserSession, and enforces
    CSRF on every mutating request (see _check_csrf). Raises 401 for no
    cookie / an invalid, expired or revoked one — this function makes no
    "which tenant" decision at all, see get_current_tenant_id for that."""
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise _not_authenticated()
    resolved = resolve_session(session, raw_token=raw_token)
    if resolved is None:
        raise _not_authenticated()
    _check_csrf(request, resolved.csrf_token)
    return resolved


def get_current_user(current: AuthenticatedSession = Depends(get_current_session)) -> User:
    return current.user


def _tenant_id_from_header_unauthenticated(x_tenant_id: str, session: Session) -> UUID:
    """The ORIGINAL (pre-A2) behavior, preserved under this explicit name
    for exactly two callers: (1) the temporary
    LEGACY_TENANT_HEADER_AUTH_ENABLED compatibility path below, used only
    for a caller presenting NO session cookie at all during the A2
    deploy-to-cutover window (see app.config.Settings.
    legacy_tenant_header_auth_enabled's own docstring); (2) existing tests
    that exercise tenant-scoped business logic and intentionally bypass
    authentication itself via `app.dependency_overrides[get_current_tenant_id]`,
    the same idiom this codebase already uses for get_session/
    get_rate_limiter — those tests are about repository/service behavior,
    not about auth, which the dedicated app.auth test suite covers."""
    try:
        tenant_uuid = UUID(x_tenant_id)
    except ValueError as exc:
        raise AppError(
            "X-Tenant-Id header must be a valid UUID.", code="invalid_tenant_header", status_code=400
        ) from exc
    if TenantRepository(session).get(tenant_uuid) is None:
        raise _unknown_tenant()
    return tenant_uuid


def get_current_tenant_id(
    request: Request,
    x_tenant_id: Annotated[str, Header()],
    session: Session = Depends(get_session),
) -> UUID:
    """The tenant-authorization boundary (A2). `X-Tenant-Id` is now only a
    SELECTION HINT — which of the caller's own authorized tenants this
    request acts as — never authorization on its own:

        requested_tenant = X-Tenant-Id
        authenticated_user = session.user          (see get_current_session)
        if not TenantAccess.exists(user, requested_tenant): DENY (404)

    A request with NO session cookie at all is authenticated exactly
    nowhere and gets 401 — UNLESS settings.legacy_tenant_header_auth_enabled
    is True, a temporary, explicit, off-by-default migration-compatibility
    switch (see that setting's own docstring); a request that DOES present
    a session is always subject to the real check above regardless of that
    flag. Every downstream service/repository call continues to receive a
    plain, trusted `tenant_id` exactly as before — this function is the
    only thing that changed.
    """
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token is None:
        if settings.legacy_tenant_header_auth_enabled:
            return _tenant_id_from_header_unauthenticated(x_tenant_id, session)
        raise _not_authenticated()

    resolved = resolve_session(session, raw_token=raw_token)
    if resolved is None:
        raise _not_authenticated()
    _check_csrf(request, resolved.csrf_token)

    try:
        tenant_uuid = UUID(x_tenant_id)
    except ValueError as exc:
        raise AppError(
            "X-Tenant-Id header must be a valid UUID.", code="invalid_tenant_header", status_code=400
        ) from exc

    if not TenantAccessRepository(session).exists(user_id=resolved.user.id, tenant_id=tenant_uuid):
        raise _unknown_tenant()

    return tenant_uuid


def get_business_analyzer() -> BusinessAnalyzer:
    """Built fresh per request rather than at import time, so a server
    without ANTHROPIC_API_KEY configured still starts up fine — it only
    fails, loudly and with a clean 503, the first time this route is
    actually called (same shape as verify_internal_automation_token
    below for INTERNAL_AUTOMATION_TOKEN)."""
    if not settings.anthropic_api_key:
        raise AppError(
            "The AI Business Analyzer is not configured on this server.",
            code="business_analyzer_not_configured",
            status_code=503,
        )
    return business_analyzer_from_settings(settings)


def get_n8n_client() -> N8nClient:
    """Built fresh per request, same shape as get_business_analyzer above:
    a server without N8N_BASE_URL/N8N_API_KEY configured still starts up
    fine — activation only fails, loudly and with a clean 503, the first
    time someone actually tries it. Never logs either value."""
    if not settings.n8n_base_url or not settings.n8n_api_key:
        raise AppError(
            "n8n is not configured on this server.",
            code="n8n_not_configured",
            status_code=503,
        )
    return N8nClient(settings.n8n_base_url, settings.n8n_api_key)


def get_optional_n8n_client() -> N8nClient | None:
    """Like get_n8n_client above, but returns None instead of raising
    when n8n isn't configured — for routes where n8n is only needed
    *conditionally*. DELETE /businesses/{id} (app.routers.businesses) is
    the one caller: it only needs n8n at all when the business being
    deleted happens to have an active automation to deactivate first: a
    business with no automation, or with automation that was never
    activated, must still be deletable on a server that has never
    configured n8n. A route that unconditionally requires n8n (activate/
    deactivate themselves) should keep using get_n8n_client instead."""
    if not settings.n8n_base_url or not settings.n8n_api_key:
        return None
    return N8nClient(settings.n8n_base_url, settings.n8n_api_key)


def get_website_publisher() -> WebsitePublisher:
    """Built fresh per request, same shape as get_n8n_client above: a
    server without CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN configured
    still starts up fine — publishing only fails, loudly and with a
    clean 503, the first time someone actually tries it. Never logs
    either value."""
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        raise AppError(
            "Website publishing is not configured on this server.",
            code="website_publisher_not_configured",
            status_code=503,
        )
    client = CloudflarePagesClient(settings.cloudflare_account_id, settings.cloudflare_api_token)
    return CloudflarePagesPublisher(
        client, account_id=settings.cloudflare_account_id, api_token=settings.cloudflare_api_token
    )


def get_domain_provider() -> DomainProvider:
    """Same shape as get_website_publisher above — the same Cloudflare
    account/token already required to publish a website is what custom-
    domain attachment needs too, so this fails the same clean, loud way
    when unconfigured rather than a second, separate "not set up" path."""
    if not settings.cloudflare_account_id or not settings.cloudflare_api_token:
        raise AppError(
            "Custom domains are not configured on this server.",
            code="domain_provider_not_configured",
            status_code=503,
        )
    client = CloudflarePagesClient(settings.cloudflare_account_id, settings.cloudflare_api_token)
    return CloudflarePagesDomainProvider(client)


def get_optional_notification_sender() -> NotificationSender | None:
    """Unlike get_website_publisher/get_n8n_client above, this never
    raises for "not configured" — returns None instead. Website publish
    and automation activation are explicit, one-shot human actions with
    no valid "silently skip" outcome, so failing loudly there is right.
    Every lead triggers notification.send, though, and not having a
    provider configured yet is a completely normal state for a business
    that hasn't set up email notifications — app.notifications.service's
    deliver_internal_notification treats None as "nothing to attempt",
    the same as a business with no contact email, never as a failure.

    Provider selection: ResendNotificationSender (HTTPS — reachable from
    serverless/edge deployment targets that block or don't reliably
    support raw outbound SMTP) is preferred whenever RESEND_API_KEY/
    RESEND_FROM_ADDRESS are configured. SmtpNotificationSender
    (app.notifications.smtp) remains available purely as a local/dev
    fallback for an operator without a Resend account yet — production
    is expected to configure Resend. Never logs either provider's
    credentials.
    """
    if settings.resend_api_key and settings.resend_from_address:
        return ResendNotificationSender(
            api_key=settings.resend_api_key,
            from_address=settings.resend_from_address,
        )
    if not settings.smtp_host or not settings.smtp_from_address:
        return None
    return SmtpNotificationSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_address=settings.smtp_from_address,
        username=settings.smtp_username,
        password=settings.smtp_password,
    )


def get_internal_creative_provider() -> InternalCreativeProvider:
    """Unlike every other provider factory in this module, InternalCreativeProvider
    needs no credentials and is always available — it wraps this
    codebase's own existing generation pipeline (see
    app.creative.internal's docstring), never an external service."""
    return InternalCreativeProvider()


def get_higgsfield_provider() -> HiggsfieldCreativeProvider:
    """Built fresh per request, same shape as get_website_publisher
    above: a server without HIGGSFIELD_API_KEY/HIGGSFIELD_BASE_URL
    configured still starts up fine — premium creative generation only
    fails, loudly and with a clean 503, the first time it's actually
    attempted. Configuring these does not make Higgsfield generation
    actually work yet — see app.creative.higgsfield.provider's own
    docstring for why every call still raises until a real API contract
    is wired in."""
    if not settings.higgsfield_api_key or not settings.higgsfield_base_url:
        raise AppError(
            "Higgsfield is not configured on this server.",
            code="higgsfield_not_configured",
            status_code=503,
        )
    client = HiggsfieldClient(settings.higgsfield_api_key, settings.higgsfield_base_url)
    return HiggsfieldCreativeProvider(client)


def get_manual_review_provider() -> ManualReviewProvider:
    """Always available — manual review import needs no credentials at
    all (same shape as get_internal_creative_provider above)."""
    return ManualReviewProvider()


def get_google_review_provider() -> GoogleReviewProvider:
    """Unlike get_higgsfield_provider above, this never raises — nothing
    in this codebase actually calls Google's API yet (see
    app.reviews.provider's own docstring), so there is no "fails loud
    when used" moment to guard; the provider's own is_available()/
    unavailable_reason() are what GET .../review-providers reads."""
    return GoogleReviewProvider(api_key=settings.google_reviews_api_key, place_id=settings.google_reviews_place_id)


def get_generated_artifact_fetcher() -> ArtifactFetcher:
    """How Image QA obtains a generated image's bytes (P2.7): a bounded https
    fetch of the provider's result URL. A dependency of its own so tests can
    substitute it — no test may reach the real network."""
    return HttpsArtifactFetcher(timeout_seconds=settings.visual_qa_fetch_timeout_seconds)


def get_generated_image_qa(
    fetcher: ArtifactFetcher = Depends(get_generated_artifact_fetcher),
) -> GeneratedImageQAService | None:
    """None when VISUAL_QA_ENABLED=false (the kill switch): generation is then
    exactly as before P2.7 and directions carry no `visual_qa` record."""
    return GeneratedImageQAService(fetcher) if settings.visual_qa_enabled else None


def get_storage_provider() -> StorageProvider:
    """PRODUCTION (P2.1): CloudflareR2StorageProvider (app.storage.r2)
    whenever all four r2_* settings are configured — persistent object
    storage, since Railway's own local filesystem is ephemeral and would
    silently lose GenerativeWebsiteArtifact source archives and Visual QA
    screenshots on every redeploy. DEV/TEST default: LocalStorageProvider
    (app.storage.local) needs no credentials at all and has a real
    default (settings.local_storage_dir), so asset upload still works out
    of the box without any account/configuration, the same way
    sqlite:///./dev.db does — never a silent, half-configured R2
    attempt."""
    account_id, access_key_id, secret_access_key, bucket_name = (
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket_name,
    )
    if account_id and access_key_id and secret_access_key and bucket_name:
        return CloudflareR2StorageProvider(
            account_id=account_id,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            bucket_name=bucket_name,
            public_base_url=settings.r2_public_base_url or "",
        )
    return LocalStorageProvider(root_dir=Path(settings.local_storage_dir))


def get_analytics_provider(session: Session = Depends(get_session)) -> AnalyticsProvider:
    """Always available, like get_storage_provider above — the internal
    event collector needs no external account/credentials (see
    app.analytics_events.provider's own docstring for why this is
    deliberately the only AnalyticsProvider implementation today)."""
    return InternalAnalyticsProvider(session)


def get_optional_higgsfield_provider() -> CreativeProvider | None:
    """Like get_higgsfield_provider above, but returns None instead of
    raising when Higgsfield isn't configured — for
    app.creative.orchestrator.select_provider, where a BASIC/PROFESSIONAL
    generation request never needs Higgsfield at all, and a business
    that never configured it must still be able to generate at those
    levels. A route that specifically requires Higgsfield should use
    get_higgsfield_provider instead."""
    if not settings.higgsfield_api_key or not settings.higgsfield_base_url:
        return None
    return get_higgsfield_provider()


def get_internal_creative_director() -> InternalCreativeDirector:
    """Always available — same shape as get_internal_creative_provider
    above (P2's CreativeDirectorProvider fallback)."""
    return InternalCreativeDirector()


def get_optional_higgsfield_director(
    storage: StorageProvider = Depends(get_storage_provider),
) -> CreativeDirectorProvider | None:
    """Returns None (never raises) when neither production nor dev
    Higgsfield configuration is present — app.creative.director_orchestrator
    falls back to get_internal_creative_director when this returns None,
    never silently presenting that fallback as a successful Higgsfield run
    (P2.14).

    PRODUCTION (P2.1): prefers the official REST API
    (app.creative.higgsfield.api_client.HiggsfieldApiClient) whenever
    HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are configured — a
    server-side credential pair, safe to run unattended. `storage` is the
    same StorageProvider app.routers.creative's own upload endpoints use
    (Phase 5: private provider references) — passed through so the
    director can mint a short-lived presigned URL for a business asset it
    recognizes as its own (asset.storage_provider matching), never a
    second, independently-configured storage client.

    DEV/LOCAL ONLY: falls back to the `higgsfield` CLI's own local OAuth
    session (higgsfield_cli_enabled — see that setting's own docstring for
    why this path is never selected in production) only when the REST
    credential pair above isn't set."""
    if settings.higgsfield_api_key_id and settings.higgsfield_api_key_secret:
        client = HiggsfieldApiClient(
            key_id=settings.higgsfield_api_key_id,
            key_secret=settings.higgsfield_api_key_secret,
            base_url=settings.higgsfield_api_base_url,
            timeout_seconds=settings.higgsfield_api_timeout_seconds,
        )
        return HiggsfieldApiCreativeDirector(
            client,
            job_type=settings.higgsfield_api_model,
            estimated_credits_per_call=settings.higgsfield_api_estimated_credits_per_call,
            asset_base_url=settings.internal_api_base_url,
            storage=storage,
            presigned_url_expires_in_seconds=settings.higgsfield_reference_presigned_url_expires_in_seconds,
        )
    if settings.higgsfield_cli_enabled:
        cli = HiggsfieldCli(
            binary=settings.higgsfield_cli_binary, timeout_seconds=settings.higgsfield_cli_timeout_seconds
        )
        return HiggsfieldCliCreativeDirector(cli, local_storage_root=Path(settings.local_storage_dir))
    return None


def get_creative_director(
    storage: StorageProvider = Depends(get_storage_provider),
) -> CreativeDirectorProvider:
    """The single creative-director selection point a router calls
    (app.routers.creative) — prefers Higgsfield when configured, wrapped
    in FallbackCreativeDirector (app.creative.director_fallback) so a
    Higgsfield workspace/config problem caught before any billable
    generation is accepted degrades to InternalCreativeDirector instead of
    making the whole workflow unusable. Always constructs successfully
    (mirrors get_internal_creative_provider's 'never fails to construct'
    shape): there is no 'creative direction unavailable' state, only a
    cheaper/more expensive one. Each returned CreativeDirection's own
    `provider_metadata['provider']` tells a caller which one actually ran
    for that candidate — never silently presented as the other (P2.14).
    `storage` is threaded into get_optional_higgsfield_director exactly as
    before FallbackCreativeDirector existed (Phase 5: private provider
    references) — wrapping the primary director for fallback purposes
    must never drop its own R2 presigned-URL wiring."""
    return FallbackCreativeDirector(
        primary=get_optional_higgsfield_director(storage), fallback=get_internal_creative_director()
    )


def get_frontend_engineer(
    storage: StorageProvider = Depends(get_storage_provider),
) -> FrontendEngineer:
    """Built fresh per request, same shape as get_business_analyzer: a
    server without ANTHROPIC_API_KEY configured still starts up fine —
    generation only fails, loudly and with a clean 503, the first time a
    generative website-draft is actually requested."""
    if not settings.anthropic_api_key:
        raise AppError(
            "The AI Frontend Engineer is not configured on this server.",
            code="frontend_engineer_not_configured",
            status_code=503,
        )
    return frontend_engineer_from_settings(settings, storage=storage)


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def rate_limit_dependency(*, key_prefix: str, limit_attr: str, window_seconds: float = 60.0) -> Callable[..., None]:
    """Builds a FastAPI dependency enforcing a sliding-window rate limit,
    keyed by `key_prefix` + the caller's IP. `limit_attr` names a
    `Settings` field read *at call time* (not when the route is defined)
    so tests can monkeypatch it and a deployment can tune it via env vars
    without a code change — see app.config.Settings'
    public_lead_rate_limit_per_minute/asset_upload_rate_limit_per_minute.
    """

    def _dependency(request: Request, limiter: RateLimiter = Depends(get_rate_limiter)) -> None:
        limit = getattr(settings, limit_attr)
        client_host = request.client.host if request.client else "unknown"
        try:
            limiter.check(f"{key_prefix}:{client_host}", limit=limit, window_seconds=window_seconds)
        except RateLimitExceededError as exc:
            raise AppError(
                "Too many requests — please try again shortly.",
                code="rate_limited",
                status_code=429,
            ) from exc

    return _dependency


def verify_internal_automation_token(
    x_internal_automation_token: Annotated[str | None, Header()] = None,
) -> None:
    """Service-to-service auth for /internal/* (app.routers.internal_automation)
    — proves the caller is our own n8n workflow (via the
    INTERNAL_AUTOMATION_TOKEN it's configured to send), not a public
    caller. Separate from get_current_tenant_id above: this checks *who
    is calling* (n8n vs. anyone), not *which tenant*; the request body's
    tenant_id/business_id still get validated against real rows by the
    route itself (Business.get(tenant_id, business_id)) — this
    dependency alone does not vouch for those ids. Uses
    hmac.compare_digest for a constant-time comparison; never logs
    either the expected or received token.
    """
    expected = settings.internal_automation_token
    if not expected:
        raise AppError(
            "Internal automation is not configured on this server.",
            code="internal_automation_not_configured",
            status_code=503,
        )
    if not x_internal_automation_token or not hmac.compare_digest(x_internal_automation_token, expected):
        raise AppError("Invalid internal automation token.", code="invalid_internal_automation_token", status_code=401)
