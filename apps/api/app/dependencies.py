import hmac
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.analysis.analyzer import BusinessAnalyzer
from app.analysis.claude.engine import business_analyzer_from_settings
from app.automation.n8n import N8nClient
from app.config import settings
from app.db.session import make_engine, make_session_factory
from app.errors import AppError
from app.notifications.resend import ResendNotificationSender
from app.notifications.sender import NotificationSender
from app.notifications.smtp import SmtpNotificationSender
from app.publishing.cloudflare import CloudflarePagesClient, CloudflarePagesPublisher
from app.publishing.publisher import WebsitePublisher
from app.repositories.tenant import TenantRepository

# Module-level: one engine/pool for the process lifetime, per SQLAlchemy's
# own recommendation (an Engine is meant to be created once, not per
# request). Tests override get_engine/get_session via FastAPI's
# dependency_overrides rather than reaching into these globals directly.
engine: Engine = make_engine(settings.database_url)
_session_factory = make_session_factory(engine)


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


def get_current_tenant_id(
    x_tenant_id: Annotated[str, Header()],
    session: Session = Depends(get_session),
) -> UUID:
    """**NOT AUTHENTICATION.** No login, session, or token verification
    exists anywhere in this codebase yet — this reads a caller-supplied
    `X-Tenant-Id` header and confirms it names a real Tenant, nothing
    more. Any caller can put any tenant's id in this header and be
    treated as that tenant; there is no check that they're actually a
    member of it. Every tenant-scoped route depends on this function
    rather than reading the header directly, so that wiring real
    authentication later (extracting tenant_id from a verified
    session/JWT instead) means changing only this function's body — no
    route or service code needs to change. Until that happens, do not
    expose any route that depends on this to an untrusted caller; treat
    it as an internal-only API boundary.
    """
    try:
        tenant_uuid = UUID(x_tenant_id)
    except ValueError as exc:
        raise AppError(
            "X-Tenant-Id header must be a valid UUID.", code="invalid_tenant_header", status_code=400
        ) from exc

    if TenantRepository(session).get(tenant_uuid) is None:
        raise AppError("Unknown tenant.", code="unknown_tenant", status_code=404)

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
