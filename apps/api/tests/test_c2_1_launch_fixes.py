"""C2.1 — first-client launch fixes.

1. Consent: a business with lead_management.consent_required refuses a lead
   without consent (422), after the silent spam drop and before preview
   suppression; without the flag nothing changes.
2. Exactly-once notifications: the public lead route is the authoritative
   sender and commits before dispatching to n8n; n8n's callbacks
   (/internal/notifications, /internal/leads/{id}/acknowledgement-email)
   only retry an attempt that did not succeed.
3. Legal publication gate mirroring legal-es.ts's pending facts.
4. SEO plumbing: locale/siteUrl survive the payload, canonical origin only
   from an ACTIVE custom domain, *.pages.dev noindex, legacy redirects.
5. Image dimensions recorded at upload and exposed on read.
6. Trusted-proxy client IP for rate-limit keys.
"""

import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.business_asset import BusinessAsset
from app.db.models.custom_domain import CustomDomain
from app.db.models.internal_notification import InternalNotification
from app.db.models.workflow import Workflow
from app.dependencies import get_optional_notification_sender, get_rate_limiter, get_session
from app.domain.business_config import BusinessConfig
from app.domain.enums import (
    AssetCategory,
    AssetKind,
    AssetOrigin,
    DomainStatus,
    NotificationDeliveryStatus,
    WorkflowStatus,
)
from app.errors import AppError
from app.main import app
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender
from app.publishing.build import _read_artifact
from app.publishing.legal_readiness import (
    SPANISH_LEGAL_FACTS,
    require_legal_facts_for_publication,
    spanish_legal_pending_facts,
)
from app.publishing.readiness import _legal_facts_check
from app.publishing.security_headers import generate_headers_file
from app.publishing.site_url import canonical_site_url
from app.repositories.lead import LeadRepository
from app.schemas.creative import BusinessAssetRead
from app.schemas.site_config import SiteConfigPayload
from app.security.client_ip import client_ip, parse_trusted_proxies
from app.security.rate_limit import InMemoryRateLimiter
from app.storage.image_validation import raster_dimensions

TOKEN = "test-internal-automation-token"
INTERNAL = {"X-Internal-Automation-Token": TOKEN}
OWNER = "dueno@ejemplo.example"
VISITOR = "visitante@ejemplo.example"


class _Sender(NotificationSender):
    def __init__(self) -> None:
        self.sent: list[NotificationEmail] = []
        self.fail_next = 0

    def send(self, message: NotificationEmail) -> None:
        if self.fail_next:
            self.fail_next -= 1
            raise NotificationSenderError("simulated provider failure")
        self.sent.append(message)

    def to(self, address: str) -> list[NotificationEmail]:
        return [message for message in self.sent if message.to == address]


def _config(**lead_management: object) -> dict:
    return {
        "schema_version": 1,
        "business_profile": {
            "name": "Reformas Valencia",
            "slug": "reformas-valencia",
            "industry": "home_renovation",
            "contact": {"email": OWNER},
        },
        "lead_management": {"enabled": True, "sources": ["website_form"], **lead_management},
        "communications": {
            "internal_notifications": {"email": True},
            "customer_notifications": {"email": True},
        },
    }


@pytest.fixture()
def sender():
    fake = _Sender()
    app.dependency_overrides[get_optional_notification_sender] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_optional_notification_sender, None)


@pytest.fixture()
def client(session, monkeypatch: pytest.MonkeyPatch):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    monkeypatch.setattr(settings, "internal_automation_token", TOKEN)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


def _lead(**overrides: object) -> dict:
    payload = {
        "name": "Maria",
        "email": VISITOR,
        "message": "Quiero un presupuesto.",
        "rendered_at": (datetime.now(UTC) - timedelta(seconds=10)).isoformat(),
    }
    payload.update(overrides)
    return payload


def _leads(session: Session, business):
    return LeadRepository(session).list_for_business(business.tenant_id, business.id)


# --- 1. consent ---------------------------------------------------------------


def test_consent_required_refuses_a_lead_without_consent_and_stores_nothing(client, session, business, sender):
    business.config = _config(consent_required=True)
    session.flush()

    response = client.post(f"/public/businesses/{business.id}/leads", json=_lead(consent=False))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "consent_required"
    assert _leads(session, business) == []
    assert sender.sent == []


def test_consent_required_accepts_a_lead_with_consent(client, session, business, sender):
    business.config = _config(consent_required=True)
    session.flush()

    response = client.post(f"/public/businesses/{business.id}/leads", json=_lead(consent=True))

    assert response.status_code == 201
    [lead] = _leads(session, business)
    assert lead.consent_given is True


def test_without_the_flag_a_lead_without_consent_is_still_accepted(client, session, business, sender):
    """Backward compatibility: a site already live without a checkbox keeps working."""
    business.config = _config()
    session.flush()

    response = client.post(f"/public/businesses/{business.id}/leads", json=_lead(consent=False))

    assert response.status_code == 201
    assert len(_leads(session, business)) == 1


def test_spam_is_still_dropped_silently_before_the_consent_check(client, session, business, sender):
    business.config = _config(consent_required=True)
    session.flush()

    response = client.post(f"/public/businesses/{business.id}/leads", json=_lead(consent=False, company_website="x"))

    assert response.status_code == 201
    assert _leads(session, business) == []


def test_a_preview_submission_is_validated_like_production(client, session, business, sender):
    business.config = _config(consent_required=True)
    session.flush()

    response = client.post(
        f"/public/businesses/{business.id}/leads",
        json=_lead(consent=False),
        headers={"Origin": "https://abc123.gwa-draft-previews.pages.dev"},
    )

    assert response.status_code == 422


# --- 2. exactly-once notifications ------------------------------------------------


def _n8n_callbacks(client: TestClient, business, lead_id: uuid.UUID) -> None:
    ids = {"tenant_id": str(business.tenant_id), "business_id": str(business.id)}
    client.post("/internal/notifications", json={**ids, "source": "website_form", "id": str(lead_id)}, headers=INTERNAL)
    client.post(f"/internal/leads/{lead_id}/acknowledgement-email", json=ids, headers=INTERNAL)


def test_n8n_callbacks_after_a_successful_public_send_never_email_again(client, session, business, sender):
    business.config = _config()
    session.flush()

    assert client.post(f"/public/businesses/{business.id}/leads", json=_lead()).status_code == 201
    [lead] = _leads(session, business)
    for _ in range(3):  # n8n's own retries included
        _n8n_callbacks(client, business, lead.id)

    assert len(sender.to(OWNER)) == 1
    assert len(sender.to(VISITOR)) == 1
    notifications = session.query(InternalNotification).filter_by(lead_id=lead.id).all()
    assert [notification.delivered for notification in notifications] == [True]


def test_n8n_retries_a_failed_public_send_exactly_once(client, session, business, sender):
    business.config = _config()
    session.flush()
    sender.fail_next = 2  # both emails fail on the public route

    assert client.post(f"/public/businesses/{business.id}/leads", json=_lead()).status_code == 201
    [lead] = _leads(session, business)
    assert lead.acknowledgement_status == NotificationDeliveryStatus.FAILED
    assert sender.sent == []

    for _ in range(3):
        _n8n_callbacks(client, business, lead.id)

    assert len(sender.to(OWNER)) == 1
    assert len(sender.to(VISITOR)) == 1
    session.refresh(lead)
    assert lead.acknowledgement_status == NotificationDeliveryStatus.SENT


def test_a_retried_public_submission_never_sends_again(client, session, business, sender):
    business.config = _config()
    session.flush()
    submission = str(uuid.uuid4())

    for _ in range(3):
        response = client.post(f"/public/businesses/{business.id}/leads", json=_lead(submission_id=submission))
        assert response.status_code == 201

    assert len(_leads(session, business)) == 1
    assert len(sender.to(OWNER)) == 1
    assert len(sender.to(VISITOR)) == 1


def test_the_lead_and_its_email_outcomes_are_committed_before_n8n_dispatch(
    client, session, business, sender, monkeypatch: pytest.MonkeyPatch
):
    business.config = _config()
    session.add(
        Workflow(
            tenant_id=business.tenant_id,
            business_id=business.id,
            name="Lead capture",
            status=WorkflowStatus.ACTIVE,
            local_workflow_id="lc",
            n8n_workflow_id="42",
        )
    )
    session.flush()
    monkeypatch.setattr("app.routers.public.settings.n8n_base_url", "https://n8n.example.com")
    events: list[str] = []
    real_commit = session.commit

    def _commit() -> None:
        events.append("commit")
        real_commit()

    monkeypatch.setattr(session, "commit", _commit)
    monkeypatch.setattr("app.routers.public.dispatch_lead_to_workflow", lambda **kwargs: events.append("dispatch"))

    assert client.post(f"/public/businesses/{business.id}/leads", json=_lead()).status_code == 201
    assert "dispatch" in events
    assert "commit" in events[: events.index("dispatch")]


# --- 3. legal publication gate ----------------------------------------------------


FULL_LEGAL = {
    "legal_name": "Ana Pérez García",
    "tax_id": "12345678Z",
    "address": {"street_address": "Calle Ejemplo 1", "locality": "Valencia", "postal_code": "46001", "country": "ES"},
    "privacy_contact_email": "privacidad@ejemplo.example",
    "data_retention": "12 meses",
}
SPANISH_SITE = {
    "locale": "es",
    "pages": [{"path": "/", "blocks": [{"type": "contact", "content": {"form": {"fields": []}}}]}],
}


def test_pending_facts_match_the_generator_ids_and_order():
    config = BusinessConfig.model_validate({"business_profile": {"name": "X", "slug": "x", "industry": "other"}})
    assert spanish_legal_pending_facts(config, has_contact_form=True) == list(SPANISH_LEGAL_FACTS)
    assert spanish_legal_pending_facts(config, has_contact_form=False) == [
        "legal_name",
        "tax_id",
        "address",
        "contact_email",
    ]


def test_complete_facts_with_consent_have_nothing_pending():
    config = BusinessConfig.model_validate({**_config(consent_required=True), "legal_profile": FULL_LEGAL})
    assert spanish_legal_pending_facts(config, has_contact_form=True) == []


def test_publication_is_refused_while_facts_are_pending(session, business):
    business.config = _config()
    session.flush()
    with pytest.raises(AppError) as error:
        require_legal_facts_for_publication(
            session=session, tenant_id=business.tenant_id, business_id=business.id, site_config=SPANISH_SITE
        )
    assert error.value.code == "legal_facts_incomplete"
    assert error.value.status_code == 409


def test_publication_is_allowed_once_every_fact_is_provided(session, business):
    business.config = {**_config(consent_required=True), "legal_profile": FULL_LEGAL}
    session.flush()
    require_legal_facts_for_publication(
        session=session, tenant_id=business.tenant_id, business_id=business.id, site_config=SPANISH_SITE
    )


def test_the_gate_does_not_apply_to_english_or_legacy_site_configs(session, business):
    business.config = _config()
    session.flush()
    for site_config in ({**SPANISH_SITE, "locale": "en"}, {"pages": SPANISH_SITE["pages"]}, None):
        require_legal_facts_for_publication(
            session=session, tenant_id=business.tenant_id, business_id=business.id, site_config=site_config
        )


def test_readiness_reports_the_same_pending_facts_as_blocking():
    check = _legal_facts_check(_config())
    assert check.blocking is True
    assert check.ready is False
    assert "NIF" in check.detail
    assert _legal_facts_check({**_config(consent_required=True), "legal_profile": FULL_LEGAL}).ready is True


# --- 4. SEO plumbing ----------------------------------------------------------------


def _site_payload(**extra: object) -> dict:
    return {
        "brand": {"name": "X"},
        "theme": {
            "colors": {
                "primary": "#000000",
                "secondary": "#111111",
                "accent": "#222222",
                "background": "#ffffff",
                "foreground": "#000000",
            },
            "fonts": {"sans": "system-ui"},
            "radius": {"base": "0.5rem", "lg": "1rem"},
        },
        "seo": {"title": "X", "description": "Y"},
        "pages": [{"path": "/", "blocks": []}],
        **extra,
    }


def test_locale_and_site_url_survive_the_payload_and_stay_omitted_when_unset():
    payload = SiteConfigPayload.model_validate(_site_payload(locale="es", siteUrl="https://a.example"))
    dumped = payload.model_dump(mode="json")
    assert dumped["locale"] == "es"
    assert dumped["siteUrl"] == "https://a.example"
    without = SiteConfigPayload.model_validate(_site_payload()).model_dump(mode="json")
    assert "locale" not in without
    assert "siteUrl" not in without


def test_canonical_site_url_comes_only_from_an_active_custom_domain(session, business):
    ids = {"session": session, "tenant_id": business.tenant_id, "business_id": business.id}
    assert canonical_site_url(**ids) is None
    domain = CustomDomain(
        tenant_id=business.tenant_id,
        business_id=business.id,
        domain="Tienda.Example.",
        status=DomainStatus.PENDING_VERIFICATION,
    )
    session.add(domain)
    session.flush()
    assert canonical_site_url(**ids) is None
    domain.status = DomainStatus.ACTIVE
    session.flush()
    assert canonical_site_url(**ids) == "https://tienda.example"


def test_pages_dev_hosts_are_noindexed_only_when_a_custom_domain_is_canonical():
    with_domain = generate_headers_file(canonical_site_url="https://tienda.example").decode()
    assert "https://:project.pages.dev/*\n  X-Robots-Tag: noindex" in with_domain
    for origin in (None, "https://site-abc.pages.dev"):
        assert "X-Robots-Tag" not in generate_headers_file(canonical_site_url=origin).decode()


def _write(root, *relatives: str) -> None:
    for relative in relatives:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html></html>")


def test_legacy_english_legal_paths_redirect_to_the_spanish_pages(tmp_path):
    _write(tmp_path, "index.html", "privacidad/index.html", "aviso-legal/index.html", "404.html")
    artifact = _read_artifact(tmp_path)
    assert artifact.files["_redirects"].decode() == "/privacy /privacidad/ 301\n/terms /aviso-legal/ 301\n"


def test_no_redirects_for_an_english_build(tmp_path):
    _write(tmp_path, "index.html", "privacy/index.html")
    assert "_redirects" not in _read_artifact(tmp_path).files


# --- 5. image dimensions --------------------------------------------------------------


def _jpeg(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_raster_dimensions_reads_the_header_and_never_raises():
    assert raster_dimensions(_jpeg(40, 30)) == (40, 30)
    assert raster_dimensions(b"not an image") is None


def test_asset_read_exposes_valid_dimensions_from_metadata_only(session, business):
    def asset(metadata: dict | None) -> BusinessAssetRead:
        row = BusinessAsset(
            tenant_id=business.tenant_id,
            business_id=business.id,
            kind=AssetKind.IMAGE,
            category=AssetCategory.GALLERY,
            origin=AssetOrigin.UPLOADED,
            storage_url="https://example.com/a.jpg",
            asset_metadata=metadata,
        )
        session.add(row)
        session.flush()
        return BusinessAssetRead.model_validate(row)

    sized = asset({"width": 1200, "height": 900})
    assert (sized.width, sized.height) == (1200, 900)
    for metadata in (None, {"width": 0, "height": 10}, {"width": "1200", "height": 900}, {"width": True, "height": 2}):
        read = asset(metadata)
        assert (read.width, read.height) == (None, None)


# --- 6. trusted-proxy client IP ----------------------------------------------------------


RAILWAY = parse_trusted_proxies("100.64.0.0/10")


def test_without_trusted_proxies_the_peer_address_is_used():
    assert client_ip("100.64.0.7", "203.0.113.9", ()) == "100.64.0.7"


def test_a_trusted_proxy_peer_yields_the_rightmost_untrusted_forwarded_address():
    assert client_ip("100.64.0.7", "198.51.100.1, 203.0.113.9", RAILWAY) == "203.0.113.9"
    assert client_ip("100.64.0.7", "203.0.113.9, 100.64.0.3", RAILWAY) == "203.0.113.9"


def test_forwarded_for_from_an_untrusted_peer_is_ignored():
    assert client_ip("203.0.113.50", "1.2.3.4", RAILWAY) == "203.0.113.50"


def test_a_malformed_forwarded_for_falls_back_to_the_peer():
    assert client_ip("100.64.0.7", "evil, not-an-ip", RAILWAY) == "100.64.0.7"
    assert client_ip("100.64.0.7", None, RAILWAY) == "100.64.0.7"


def test_an_invalid_trusted_proxy_setting_fails_loudly():
    with pytest.raises(ValueError):
        parse_trusted_proxies("100.64.0.0/10, not-a-cidr")


# --- 7. platform contract accepts the Spanish legal pages ---------------------------------


def test_platform_contract_accepts_spanish_legal_pages_and_still_requires_all_three():
    from app.qa.platform_contract import _check_legal_links, _check_legal_pages

    entry = '<a href="/aviso-legal">Aviso legal</a><a href="/privacidad">Privacidad</a><a href="/cookies">Cookies</a>'
    files = {
        "index.html": entry.encode(),
        "aviso-legal/index.html": b"<html></html>",
        "privacidad/index.html": b"<html></html>",
        "cookies/index.html": b"<html></html>",
    }
    assert _check_legal_pages(files) == []
    assert _check_legal_links(files, {"index.html": entry}) == []

    del files["privacidad/index.html"]
    assert [finding.message for finding in _check_legal_pages(files)] == [
        "No /privacy legal page found in the build output."
    ]
