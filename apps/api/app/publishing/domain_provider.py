"""DomainProvider — the hosting-provider-neutral interface between a
business's requested custom domain and whatever hosting provider
actually attaches it to the live site. CloudflarePagesDomainProvider
(app.publishing.cloudflare) is the first, replaceable implementation;
nothing outside app.publishing.cloudflare should need to know Cloudflare
exists. Mirrors app.publishing.publisher.WebsitePublisher's shape.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict


class DomainAttachmentResult(BaseModel):
    """Provider-neutral snapshot of one hostname's attachment state.
    `provider_status` is the hosting provider's own raw status string,
    passed through verbatim rather than reinterpreted into a finer-
    grained state this codebase doesn't actually know is true (see
    app.domain.enums.DomainStatus's own docstring for why). `is_active`
    is the one fact this codebase does assert — computed conservatively,
    never true unless the provider's response says so explicitly."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    provider_status: str
    is_active: bool
    cname_target: str
    error: str | None = None


class DomainProvider(ABC):
    @abstractmethod
    def attach(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        """Registers `domain` against the site `site_id` already
        identifies (the same identifier WebsitePublisher.publish used to
        create it) and returns its current attachment state.
        Implementations should make this idempotent: attaching a domain
        that's already attached must return its current state rather
        than erroring."""
        ...

    @abstractmethod
    def get_status(self, *, site_id: str, domain: str) -> DomainAttachmentResult:
        """Re-checks `domain`'s attachment/verification state against
        the provider — never a locally-cached guess."""
        ...

    @abstractmethod
    def detach(self, *, site_id: str, domain: str) -> None:
        """Removes `domain` from the site for real. Implementations
        should make this idempotent: detaching a domain that's already
        detached (or was never attached) must not raise."""
        ...
