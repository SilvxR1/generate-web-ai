"""WebsitePublisher — the hosting-provider-neutral interface between a
built static site artifact (real HTML/CSS/asset files — see
app.publishing.build) and whatever actually serves it live.
CloudflarePagesPublisher (app.publishing.cloudflare) is the first,
replaceable implementation; nothing outside app.publishing.cloudflare
should need to know Cloudflare exists. Mirrors
app.automation.engine.AutomationEngine's shape for the automation side
of this codebase.
"""

from abc import ABC, abstractmethod

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class WebsiteArtifact(BaseModel):
    """A real, production static-site build output — whatever
    `astro build` wrote to its `--outDir` (see app.publishing.build),
    read back as a plain path -> bytes map. Provider-neutral: nothing
    here is Cloudflare-shaped, and nothing here is a single HTML string
    — a real Astro build is index.html plus one or more hashed CSS/JS
    files, which is exactly why WebsitePublisher.publish takes this
    instead of a bare `html: str`.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # Keys are root-relative paths without a leading slash (e.g.
    # "index.html", "_astro/index.AbCd12.css") — a provider adds
    # whatever leading slash/host prefix its own API expects.
    files: dict[str, bytes]
    entry_point: str = Field(default="index.html")


class PublishedSite(BaseModel):
    """A site as it exists on the hosting provider — provider-neutral
    (no Cloudflare-specific fields). `url` is validated as a proper
    absolute URL by the field type itself, never trusted as a bare
    string from the provider's response."""

    model_config = ConfigDict(extra="forbid")

    deployment_id: str
    url: AnyHttpUrl
    live: bool


class WebsitePublisher(ABC):
    @abstractmethod
    def publish(self, *, site_id: str, artifact: WebsiteArtifact) -> PublishedSite:
        """(Re)deploys `artifact` under the stable identifier `site_id`
        and returns its live state. Implementations should make this an
        upsert keyed by `site_id` — republishing the same business
        redeploys the same site rather than accumulating new ones."""
        ...

    @abstractmethod
    def get_status(self, deployment_id: str) -> PublishedSite: ...

    @abstractmethod
    def unpublish(self, deployment_id: str) -> None:
        """Takes the deployed site down for real — the counterpart to
        `publish`, not a local-only status flip. Implementations should
        make this idempotent: unpublishing something already offline
        (or never published) must not raise. `deployment_id` is the same
        opaque identifier `publish`/`get_status` use — never touches
        this codebase's own persisted Website row, that's the caller's
        job (see app.publishing.service.unpublish_website)."""
        ...


class PreviewDeployment(BaseModel):
    """One draft preview as it exists on the hosting provider (A8.3.4.2a).
    `deployment_id` is opaque to every layer above the provider; `url` is
    that deployment's own immutable URL (never a production alias)."""

    model_config = ConfigDict(extra="forbid")

    deployment_id: str
    url: AnyHttpUrl


class PreviewPublisher(ABC):
    """Deploys a draft's EXACT stored WebsiteArtifact to an isolated,
    non-production preview location (A8.3.4.2a). Deliberately a separate
    interface from WebsitePublisher: an implementation is bound to ONE
    dedicated preview project at construction, and neither method accepts
    a project/site id — so no caller can aim a preview at a business's
    production site. It deploys the artifact byte-for-byte (no noindex
    injection, no header rewriting); preview-only policy lives in the
    hosting platform, outside the artifact."""

    @abstractmethod
    def publish_preview(self, *, branch: str, artifact: WebsiteArtifact) -> PreviewDeployment: ...

    @abstractmethod
    def retire_preview(self, *, branch: str, deployment_id: str) -> None:
        """Best-effort removal of a superseded/finished preview. Never
        touches a stored artifact."""
        ...
