"""Importing this module registers every mapped class on Base.metadata —
required before Base.metadata.create_all() (tests) or Alembic
autogenerate can see the full schema. Import order matters only in that
every class referenced by a string in a relationship() must be registered
before mappers are configured, which SQLAlchemy defers until first use, so
a flat import list here is sufficient.
"""

from app.db.models.business import Business
from app.db.models.business_asset import BusinessAsset
from app.db.models.business_review import BusinessReview
from app.db.models.creative_generation import CreativeGeneration
from app.db.models.credential import Credential
from app.db.models.execution import Execution
from app.db.models.integration import Integration
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.template import Template
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.website import Website
from app.db.models.website_draft import WebsiteDraft
from app.db.models.workflow import Workflow
from app.db.models.workflow_version import WorkflowVersion

__all__ = [
    "Business",
    "BusinessAsset",
    "BusinessReview",
    "Credential",
    "CreativeGeneration",
    "Execution",
    "InternalNotification",
    "Integration",
    "Lead",
    "Template",
    "Tenant",
    "User",
    "Website",
    "WebsiteDraft",
    "Workflow",
    "WorkflowVersion",
]
