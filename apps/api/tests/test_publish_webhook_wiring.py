"""publish_website (app.publishing.service) wiring a business's real,
active n8n webhook URL into its published contact form's `action` —
the change that makes:

    Published website -> Contact form -> n8n webhook -> internal lead callback

actually real. Covers: the URL only appears once automation is
genuinely ACTIVE, it's built from the exact slug/workflow-id
activation persisted (app.automation.n8n.lead_submitted_webhook_url,
the same helper app.automation.n8n.translator uses for the workflow's
own trigger node — no separate, duplicated path logic), that
publishing without an active automation (or without N8N_BASE_URL)
leaves the form exactly as `generateSiteConfig()` produced it rather
than fabricating a URL, and that publishing itself never fails just
because automation isn't active yet."""

import httpx
import pytest
from sqlalchemy.orm import Session

from app.automation.activation import activate_lead_capture_automation, deactivate_lead_capture_automation
from app.automation.n8n import N8nClient, lead_submitted_webhook_url
from app.config import Settings
from app.db.models.business import Business
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.enums import WebsiteStatus
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.publishing.service import publish_website
from app.schemas.site_config import SiteConfigPayload

N8N_BASE_URL = "https://n8n.example.com"
EXPECTED_WORKFLOW_ID = "reforma-casa-valencia-lead-capture"


def _n8n_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "internal_api_base_url": "http://localhost:8000",
        "n8n_base_url": N8N_BASE_URL,
        "n8n_api_key": "n8n-api-key",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _n8n_client(handler) -> N8nClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url=N8N_BASE_URL)
    return N8nClient(N8N_BASE_URL, "n8n-api-key", http_client=http_client)


def _successful_n8n_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/workflows":
        return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
    return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})


def _activate(session: Session, business: Business) -> None:
    activate_lead_capture_automation(
        session=session,
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_n8n_settings(),
        client=_n8n_client(_successful_n8n_handler),
    )


def _deactivate(session: Session, business: Business) -> None:
    deactivate_lead_capture_automation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_n8n_settings(),
        client=_n8n_client(_successful_n8n_handler),
    )


def _site_config_with_contact_form() -> SiteConfigPayload:
    return SiteConfigPayload.model_validate(
        {
            "brand": {"name": "Reforma Casa Valencia"},
            "theme": {
                "colors": {
                    "primary": "#111827",
                    "secondary": "#6b7280",
                    "accent": "#2563eb",
                    "background": "#ffffff",
                    "foreground": "#111827",
                },
                "fonts": {"sans": "Inter, sans-serif"},
                "radius": {"base": "0.5rem", "lg": "1rem"},
            },
            "seo": {"title": "Reforma Casa Valencia", "description": "Reformas en Valencia."},
            "pages": [
                {
                    "path": "/",
                    "blocks": [
                        {"type": "hero", "content": {"heading": "Hola"}},
                        {
                            "type": "contact",
                            "content": {
                                "heading": "Contacto",
                                "form": {
                                    "fields": [
                                        {"name": "name", "label": "Nombre"},
                                        {"name": "email", "label": "Email"},
                                    ]
                                },
                            },
                        },
                    ],
                }
            ],
        }
    )


class _FakePublisher(WebsitePublisher):
    def publish(self, *, site_id: str, artifact: WebsiteArtifact) -> PublishedSite:
        return PublishedSite(deployment_id=site_id, url=f"https://{site_id}.example.pages.dev", live=True)

    def get_status(self, deployment_id: str) -> PublishedSite:
        raise NotImplementedError

    def unpublish(self, deployment_id: str) -> None:
        raise NotImplementedError


def _publish(
    session: Session,
    business: Business,
    site_config: SiteConfigPayload,
    *,
    n8n_base_url: str | None,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: list[SiteConfigPayload] = []

    def _fake_build(site_config: SiteConfigPayload) -> WebsiteArtifact:
        captured.append(site_config)
        return WebsiteArtifact(files={"index.html": b"<html></html>"})

    monkeypatch.setattr("app.publishing.service.build_site", _fake_build)

    result = publish_website(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        site_config=site_config,
        publisher=_FakePublisher(),
        n8n_base_url=n8n_base_url,
    )
    return result, captured[0]


def _contact_block(built_site_config: SiteConfigPayload):
    return next(b for p in built_site_config.pages for b in p.blocks if b.type == "contact")


# --- webhook URL correctly injected -----------------------------------------


def test_webhook_url_injected_when_automation_is_active(session: Session, business: Business, monkeypatch):
    _activate(session, business)

    result, built = _publish(
        session, business, _site_config_with_contact_form(), n8n_base_url=N8N_BASE_URL, monkeypatch=monkeypatch
    )

    assert result.status is WebsiteStatus.LIVE
    action = _contact_block(built).content["form"]["action"]
    assert action == f"{N8N_BASE_URL}/webhook/lead-submitted/{EXPECTED_WORKFLOW_ID}"


# --- correct slug/workflow mapping (reuses the translator's own helper) -----


def test_injected_url_matches_the_translators_own_webhook_path_convention(
    session: Session, business: Business, monkeypatch
):
    _activate(session, business)

    _, built = _publish(
        session, business, _site_config_with_contact_form(), n8n_base_url=N8N_BASE_URL, monkeypatch=monkeypatch
    )

    action = _contact_block(built).content["form"]["action"]
    assert action == lead_submitted_webhook_url(N8N_BASE_URL, EXPECTED_WORKFLOW_ID)


# --- explicit "no fake URL" behavior -----------------------------------------


def test_no_injection_without_any_activated_automation(session: Session, business: Business, monkeypatch):
    _, built = _publish(
        session, business, _site_config_with_contact_form(), n8n_base_url=N8N_BASE_URL, monkeypatch=monkeypatch
    )

    assert "action" not in _contact_block(built).content["form"]


def test_no_injection_when_automation_was_deactivated(session: Session, business: Business, monkeypatch):
    _activate(session, business)
    _deactivate(session, business)

    _, built = _publish(
        session, business, _site_config_with_contact_form(), n8n_base_url=N8N_BASE_URL, monkeypatch=monkeypatch
    )

    assert "action" not in _contact_block(built).content["form"]


def test_no_injection_without_n8n_base_url_even_when_active(session: Session, business: Business, monkeypatch):
    _activate(session, business)

    result, built = _publish(
        session, business, _site_config_with_contact_form(), n8n_base_url=None, monkeypatch=monkeypatch
    )

    assert "action" not in _contact_block(built).content["form"]
    # Missing n8n config is handled explicitly (no fake URL) — it does
    # NOT block publishing itself.
    assert result.status is WebsiteStatus.LIVE


def test_contact_block_without_a_form_is_left_alone(session: Session, business: Business, monkeypatch):
    _activate(session, business)
    site_config = _site_config_with_contact_form()
    contact = _contact_block(site_config)
    del contact.content["form"]

    _, built = _publish(session, business, site_config, n8n_base_url=N8N_BASE_URL, monkeypatch=monkeypatch)

    assert "form" not in _contact_block(built).content
