"""CloudflarePagesDomainProvider — the first, replaceable DomainProvider
implementation (app.publishing.domain_provider). Nothing outside this
module (and client.py) knows Cloudflare exists — callers depend on
DomainProvider, the same boundary CloudflarePagesPublisher/
WebsitePublisher already establishes for the website-hosting side.

Talks only to the Cloudflare Pages custom-domains REST resource
(POST/GET/DELETE .../pages/projects/{project_name}/domains[/{domain}]),
via CloudflarePagesClient — never wrangler, never a raw DNS mutation:
this codebase never touches a customer's DNS provider directly. The
human is always the one who creates the CNAME record at their own DNS
provider, pointed at `cname_target` (the project's stable pages.dev
alias) — see DomainAttachmentResult's own docstring for why this module
never asserts more about Cloudflare's verification state than the
provider's own `status` field actually says.
"""

from app.publishing.cloudflare.client import CloudflarePagesClient
from app.publishing.cloudflare.client import validate_project_name as _validate_project_name
from app.publishing.domain_provider import DomainAttachmentResult, DomainProvider


class CloudflarePagesDomainProvider(DomainProvider):
    def __init__(self, client: CloudflarePagesClient) -> None:
        self._client = client

    def attach(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        project_name = _validate_project_name(site_id)
        # Check-first, same idempotent shape as
        # CloudflarePagesClient.ensure_project: attaching a domain
        # that's already attached returns its current state rather than
        # erroring on Cloudflare's own "domain already exists" response.
        result = self._client.get_domain(project_name, domain)
        if result is None:
            result = self._client.add_domain(project_name, domain)
        return self._to_result(project_name, domain, result)

    def get_status(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        project_name = _validate_project_name(site_id)
        result = self._client.get_domain(project_name, domain)
        if result is None:
            return DomainAttachmentResult(
                domain=domain,
                provider_status="not_attached",
                is_active=False,
                cname_target=self._cname_target(project_name),
                error="This domain is not currently attached to the Cloudflare Pages project.",
            )
        return self._to_result(project_name, domain, result)

    def detach(self, *, site_id: str, domain: str) -> None:
        project_name = _validate_project_name(site_id)
        self._client.delete_domain(project_name, domain)

    def _to_result(self, project_name: str, domain: str, result: dict) -> DomainAttachmentResult:
        # Cloudflare's own status string, never reinterpreted beyond the
        # one fact this codebase asserts (is_active) — see
        # DomainAttachmentResult's docstring.
        provider_status = str(result.get("status") or "unknown")
        return DomainAttachmentResult(
            domain=domain,
            provider_status=provider_status,
            is_active=provider_status.lower() == "active",
            cname_target=self._cname_target(project_name),
        )

    def _cname_target(self, project_name: str) -> str:
        # The same stable production alias CloudflarePagesPublisher._url_for
        # already reports as this business's live URL — Cloudflare Pages
        # custom domains are attached by CNAME'ing to this, exactly as
        # engine.py's own docstring documents.
        return f"{project_name}.pages.dev"
