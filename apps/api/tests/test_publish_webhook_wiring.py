"""publish_website (app.publishing.service) NEVER wires a business's n8n
webhook into a published contact form's `action` — the P2 continuation's
canonical-lead-API fix. Before this, an active automation's real webhook
URL was injected directly into the form so the browser posted straight
to n8n (app.publishing.service._inject_lead_capture_webhook_url, now
removed): that made n8n the only thing that ever persisted the Lead,
inverting the "lead always persists before automation" requirement, and
gave a generative site (no SiteConfig to rewrite) no equivalent path at
all.

Now every published site's contact form is left exactly as
`generateSiteConfig()` produced it (no `action`) regardless of
automation state — the browser always submits to the one canonical
POST /public/businesses/{id}/leads (app.routers.public), which persists
the Lead first and only then dispatches to n8n itself, server-side, best
-effort (see tests/test_lead_automation_dispatch.py for that half, and
app.automation.n8n.dispatch's own docstring for the full architecture).
"""

import httpx
import pytest
from sqlalchemy.orm import Session

from app.automation.activation import activate_lead_capture_automation, deactivate_lead_capture_automation
from app.automation.n8n import N8nClient
from app.config import Settings
from app.db.models.business import Business
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.enums import WebsiteStatus
from app.publishing.publisher import PublishedSite, WebsiteArtifact, WebsitePublisher
from app.publishing.service import publish_website
from app.schemas.site_config import SiteConfigPayload

N8N_BASE_URL = "https://n8n.example.com"


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


def _publish(session: Session, business: Business, site_config: SiteConfigPayload, monkeypatch: pytest.MonkeyPatch):
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
    )
    return result, captured[0]


def _contact_block(built_site_config: SiteConfigPayload):
    return next(b for p in built_site_config.pages for b in p.blocks if b.type == "contact")


# --- P2: never injected, regardless of automation state ---------------------


def test_no_webhook_injection_when_automation_is_active(session: Session, business: Business, monkeypatch):
    _activate(session, business)

    result, built = _publish(session, business, _site_config_with_contact_form(), monkeypatch)

    assert result.status is WebsiteStatus.LIVE
    assert "action" not in _contact_block(built).content["form"]


def test_no_webhook_injection_without_any_activated_automation(session: Session, business: Business, monkeypatch):
    _, built = _publish(session, business, _site_config_with_contact_form(), monkeypatch)

    assert "action" not in _contact_block(built).content["form"]


def test_no_webhook_injection_when_automation_was_deactivated(session: Session, business: Business, monkeypatch):
    _activate(session, business)
    _deactivate(session, business)

    _, built = _publish(session, business, _site_config_with_contact_form(), monkeypatch)

    assert "action" not in _contact_block(built).content["form"]


def test_publish_website_no_longer_accepts_an_n8n_base_url_parameter(session: Session, business: Business):
    """The parameter is gone entirely, not merely unused — publish_website
    has nothing left to do with it now that the browser never needs to
    know n8n exists (app.automation.n8n.dispatch is the new, server-side
    integration point)."""
    import inspect

    assert "n8n_base_url" not in inspect.signature(publish_website).parameters


def test_contact_block_without_a_form_is_left_alone(session: Session, business: Business, monkeypatch):
    _activate(session, business)
    site_config = _site_config_with_contact_form()
    contact = _contact_block(site_config)
    del contact.content["form"]

    _, built = _publish(session, business, site_config, monkeypatch)

    assert "form" not in _contact_block(built).content
