"""Website version history + rollback (P0 Phase 20-22). Every successful
app.publishing.service.publish_website call already creates one
WebsiteVersion row (see that function) — this module only reads that
history back and, for rollback, republishes an old snapshot through the
exact same publish_website() a normal publish uses.

Rollback is deliberately "just a republish of an old SiteConfig," not a
second deploy mechanism: whatever publish_website already guarantees on
failure (the current live Website state is left untouched — see
test_website_publish_service.py) applies to a failed rollback for free,
and nothing here ever deletes or rewrites a WebsiteVersion row, so
history is never lost even when a rollback attempt fails.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.publishing.publisher import WebsitePublisher
from app.publishing.service import WebsitePublishError, WebsiteStateResult, publish_website
from app.repositories.website_version import WebsiteVersionRepository
from app.schemas.site_config import SiteConfigPayload
from app.schemas.website_version import WebsiteVersionSummary


def list_website_versions(*, session: Session, tenant_id: UUID, business_id: UUID) -> list[WebsiteVersionSummary]:
    """Most recent first; the first entry (if any) is flagged
    `is_current` — never independently recomputed from the live Website
    row, since a version is created inside the very same publish
    transaction that updates it, so the two can never disagree."""
    versions = WebsiteVersionRepository(session).list_for_business(tenant_id, business_id)
    return [
        WebsiteVersionSummary(
            id=version.id, published_at=version.published_at, deploy_url=version.deploy_url, is_current=index == 0
        )
        for index, version in enumerate(versions)
    ]


def rollback_to_version(
    *,
    session: Session,
    tenant_id: UUID,
    business_id: UUID,
    version_id: UUID,
    publisher: WebsitePublisher,
    n8n_base_url: str | None = None,
) -> WebsiteStateResult:
    version = WebsiteVersionRepository(session).get_for_business(tenant_id, business_id, version_id)
    if version is None:
        raise WebsitePublishError(
            "This website version was not found.", code="website_version_not_found", status_code=404
        )

    site_config = SiteConfigPayload.model_validate(version.site_config)
    return publish_website(
        session=session,
        tenant_id=tenant_id,
        business_id=business_id,
        site_config=site_config,
        publisher=publisher,
        n8n_base_url=n8n_base_url,
    )
