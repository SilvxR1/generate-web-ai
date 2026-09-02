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
